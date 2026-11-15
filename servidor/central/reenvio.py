"""Reenvío push y heartbeat (D15, CS-002 §5).

Cada servidor en push tiene dos tareas propias: `_entregar`, que le envía los mensajes en
orden de `seq` desde su cursor guardado en SQLite, y `_latir`, que consulta su
`/fed/health`. Las tareas son independientes, así que un grupo lento o caído no frena a
los demás (salvaguarda 6).
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

import httpx

from .almacen import Almacen
from .configuracion import Configuracion
from .eventos import Evento, ahora_iso, registrar
from .modelo import LAMPORT_MAXIMO, MensajeGuardado
from .urls import motivo_destino_prohibido

registro = logging.getLogger("central")


@dataclass
class EstadoLatido:
    """Estado en memoria del heartbeat de un servidor. Al arrancar se asume vivo."""

    vivo: bool = True
    fallos_seguidos: int = 0
    caido_desde: float | None = None  # reloj monotónico
    caidas: int = 0
    _vivo: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _hay_mensajes: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _latir_ya: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def __post_init__(self) -> None:
        self._vivo.set()
        self._hay_mensajes.set()


@dataclass(frozen=True)
class _Resultado:
    entregado: bool = False
    rechazado: int | None = None  # código 4xx
    causa: str | None = None  # motivo del fallo que se reintenta


class Repartidor:
    def __init__(self, config: Configuracion, almacen: Almacen, http: httpx.AsyncClient) -> None:
        self._config = config
        self._almacen = almacen
        self._http = http
        self._estados: dict[str, EstadoLatido] = {}
        self._tareas: dict[str, list[asyncio.Task]] = {}
        self._candado = asyncio.Lock()

    # --- Ciclo de vida --------------------------------------------------------------

    async def sincronizar(self) -> None:
        """Arranca o detiene las tareas según los servidores en push registrados."""
        async with self._candado:
            servidores = await asyncio.to_thread(self._almacen.listar_servidores)
            en_push = {s.nombre for s in servidores if s.modo == "push"}
            for nombre in [n for n in self._tareas if n not in en_push]:
                await self._parar(nombre)
            for nombre in sorted(en_push - set(self._tareas)):
                estado = EstadoLatido()
                self._estados[nombre] = estado
                self._tareas[nombre] = [
                    asyncio.create_task(self._sin_caerse(self._entregar, nombre, estado),
                                        name=f"entregar-{nombre}"),
                    asyncio.create_task(self._sin_caerse(self._latir, nombre, estado),
                                        name=f"latir-{nombre}"),
                ]

    async def _parar(self, nombre: str) -> None:
        tareas = self._tareas.pop(nombre, [])
        self._estados.pop(nombre, None)
        for tarea in tareas:
            tarea.cancel()
        await asyncio.gather(*tareas, return_exceptions=True)

    async def detener(self) -> None:
        async with self._candado:
            for nombre in list(self._tareas):
                await self._parar(nombre)

    def avisar(self) -> None:
        """Llegó un mensaje nuevo: despierta todas las entregas."""
        for estado in self._estados.values():
            estado._hay_mensajes.set()

    def latir_ya(self, nombre: str) -> None:
        """Un servidor caído renovó su registro: el heartbeat no espera al siguiente periodo."""
        if (estado := self._estados.get(nombre)) and not estado.vivo:
            estado._latir_ya.set()

    def estado(self, nombre: str) -> EstadoLatido | None:
        return self._estados.get(nombre)

    async def _sin_caerse(self, corrutina, nombre: str, estado: EstadoLatido) -> None:
        """Si la tarea falla por un error del central, lo registra y la reinicia."""
        while True:
            try:
                await corrutina(nombre, estado)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                registro.exception("tarea %s de %s falló; se reinicia en 1 s", corrutina.__name__, nombre)
                await asyncio.sleep(1)

    # --- Entrega --------------------------------------------------------------------

    def _espera(self, intento: int) -> float:
        """min(máximo, base · 2ⁿ⁻¹) con jitter igual: la mitad fija y la mitad al azar."""
        tope = min(self._config.backoff_max_s, self._config.backoff_base_s * 2 ** min(intento - 1, 30))
        return tope / 2 + random.uniform(0, tope / 2)

    async def _entregar(self, nombre: str, estado: EstadoLatido) -> None:
        intento = 0
        while True:
            if not estado.vivo:
                await estado._vivo.wait()
                intento = 0  # al volver, el backoff empieza de nuevo
            estado._hay_mensajes.clear()
            mensaje = await asyncio.to_thread(self._almacen.siguiente_para, nombre)
            if mensaje is None:
                intento = 0
                await estado._hay_mensajes.wait()
                continue
            resultado = await self._enviar(nombre, mensaje)
            if resultado.entregado or resultado.rechazado is not None:
                await asyncio.to_thread(self._almacen.avanzar_cursor, nombre, mensaje.seq)
                intento = 0
                continue
            intento += 1
            espera = self._espera(intento)
            registrar(Evento.REINTENTO, id=mensaje.id, destino=nombre, intento=intento,
                      espera_s=round(espera, 3), causa=resultado.causa)
            caidas = estado.caidas
            await asyncio.sleep(espera)
            if estado.caidas != caidas:
                intento = 0

    async def _enviar(self, nombre: str, mensaje: MensajeGuardado) -> _Resultado:
        # La URL se lee en cada intento: si el grupo renovó con otro túnel, ya va a la nueva.
        servidor = await asyncio.to_thread(self._almacen.obtener_servidor, nombre)
        if servidor is None or servidor.modo != "push" or not servidor.url:
            return _Resultado(causa="sin_registro_push")
        if await motivo_destino_prohibido(servidor.url, self._config.permitir_url_privadas):
            return _Resultado(causa="destino_prohibido")
        inicio = time.monotonic()
        try:
            respuesta = await self._http.post(
                f"{servidor.url}/fed/messages", json=mensaje.como_json(),
                timeout=self._config.http_timeout_s,
            )
        except httpx.TimeoutException:
            return _Resultado(causa="timeout")
        except httpx.HTTPError as e:
            return _Resultado(causa=f"conexion:{type(e).__name__}")
        ms = round((time.monotonic() - inicio) * 1000)
        if 200 <= respuesta.status_code < 300:
            registrar(Evento.REENVIADO, id=mensaje.id, seq=mensaje.seq, destino=nombre, ms=ms)
            return _Resultado(entregado=True)
        if 400 <= respuesta.status_code < 500:
            registrar(Evento.RECHAZADO_4XX, id=mensaje.id, destino=nombre, codigo=respuesta.status_code)
            return _Resultado(rechazado=respuesta.status_code)
        return _Resultado(causa=f"http_{respuesta.status_code}")

    # --- Heartbeat ------------------------------------------------------------------

    async def _latir(self, nombre: str, estado: EstadoLatido) -> None:
        while True:
            vivo, lamport = await self._consultar_salud(nombre)
            if vivo:
                estado.fallos_seguidos = 0
                await asyncio.to_thread(self._almacen.guardar_latido, nombre, lamport, ahora_iso())
                if not estado.vivo:
                    caido_s = time.monotonic() - (estado.caido_desde or time.monotonic())
                    estado.vivo, estado.caido_desde = True, None
                    estado._vivo.set()
                    registrar(Evento.GRUPO_VOLVIO, destino=nombre, caido_s=round(caido_s, 1))
            else:
                estado.fallos_seguidos += 1
                if estado.vivo and estado.fallos_seguidos >= self._config.heartbeat_fallos_para_caido:
                    estado.vivo, estado.caido_desde = False, time.monotonic()
                    estado.caidas += 1
                    estado._vivo.clear()
                    registrar(Evento.GRUPO_CAIDO, destino=nombre, fallos=estado.fallos_seguidos)
            estado._latir_ya.clear()
            try:
                await asyncio.wait_for(estado._latir_ya.wait(), timeout=self._config.heartbeat_intervalo_s)
            except TimeoutError:
                pass

    async def _consultar_salud(self, nombre: str) -> tuple[bool, int | None]:
        """Vivo es cualquier 2xx (A11). Si el cuerpo trae un `lamport` entero, se publica."""
        servidor = await asyncio.to_thread(self._almacen.obtener_servidor, nombre)
        if servidor is None or not servidor.url:
            return False, None
        if await motivo_destino_prohibido(servidor.url, self._config.permitir_url_privadas):
            return False, None
        try:
            respuesta = await self._http.get(f"{servidor.url}/fed/health", timeout=self._config.http_timeout_s)
        except httpx.HTTPError:
            return False, None
        if not 200 <= respuesta.status_code < 300:
            return False, None
        try:
            lamport = respuesta.json().get("lamport")
        except (ValueError, AttributeError):
            return True, None
        if isinstance(lamport, int) and not isinstance(lamport, bool) and 0 <= lamport <= LAMPORT_MAXIMO:
            return True, lamport
        return True, None
