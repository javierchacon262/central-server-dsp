"""Los 9 casos de la parte automática (CS-002 §12).

Cada caso es una función `caso_N(ctx) -> Resultado`, y `CASOS` fija el orden. Ningún
caso lanza excepciones por lo que responda el grupo: una respuesta inesperada (JSON
inválido, HTML, conexión cortada) queda registrada en el resultado y el script sigue.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

# Severidad de un caso: solo los obligatorios deciden el código de salida.
OBLIGATORIO = "obligatorio"
ADVERTENCIA_SEVERIDAD = "advertencia"

# Estado de un resultado.
PASO = "paso"
FALLO = "fallo"
ADVERTENCIA = "advertencia"
NO_EVALUADO = "no_evaluado"

# Mensajes de prueba (A12): el grupo puede reconocerlos y filtrarlos por `origin`.
ORIGEN_PRUEBA = "conformidad"
REMITENTE_PRUEBA = "conformidad@conformidad"
CUERPO_PRUEBA = "[conformidad] mensaje de prueba del script de conformidad; se puede ignorar"

# Mayor marca de Lamport válida (A9).
MAX_LAMPORT = 2**53 - 1

# Campos desconocidos del caso 6: un texto, un objeto anidado y un número.
CAMPOS_DESCONOCIDOS = {
    "prioridad": "alta",
    "adjuntos": {"cantidad": 0, "tipos": ["texto"]},
    "version_cliente": 2,
}

RUTA_SALUD = "/fed/health"
RUTA_MENSAJES = "/fed/messages"


@dataclass
class Llamada:
    """Una llamada HTTP al grupo y lo que respondió."""

    caso: int
    metodo: str
    ruta: str
    codigo: int | None
    texto: str
    datos: object | None
    ms: int
    error: str | None = None
    agoto_espera: bool = False

    @property
    def es_2xx(self) -> bool:
        return self.codigo is not None and 200 <= self.codigo < 300

    @property
    def es_4xx(self) -> bool:
        return self.codigo is not None and 400 <= self.codigo < 500

    def describir(self) -> str:
        """El código y el tiempo, o el error, en una frase."""
        if self.codigo is None:
            return f"{self.error} ({self.ms} ms)"
        return f"{self.codigo} en {self.ms} ms"


@dataclass
class Resultado:
    """El resultado de un caso, tal como lo muestra el informe."""

    numero: int
    nombre: str
    severidad: str
    estado: str
    detalle: str
    codigo_http: int | None = None
    cuerpo: str | None = None
    ms: int | None = None
    enviado: str = ""
    esperado: str = ""


@dataclass
class Contexto:
    """Lo que los casos comparten durante una corrida."""

    url: str
    cliente: httpx.Client
    timeout_s: float = 3.0
    reloj: Callable[[], float] = time.monotonic
    server: str | None = None
    lamport: int | None = None
    ids_enviados: list[str] = field(default_factory=list)
    llamadas: list[Llamada] = field(default_factory=list)
    caso_actual: int = 0
    sin_respuesta: bool = False
    mensaje_caso_2: dict | None = None
    caso_2_aceptado: bool = False
    reloj_tras_caso_2: int | None = None
    _seq: int = 0

    @property
    def limite_ms(self) -> int:
        return round(self.timeout_s * 1000)

    def a_tiempo(self, llamada: Llamada) -> bool:
        return llamada.codigo is not None and llamada.ms <= self.limite_ms

    def nuevo_mensaje(self, lamport: int, *, con_id: bool = True, extra: dict | None = None) -> dict:
        """Un mensaje de prueba con los seis campos de la sección 4 más `seq` (A10)."""
        self._seq += 1
        mensaje: dict = {}
        if con_id:
            identificador = str(uuid.uuid4())
            mensaje["id"] = identificador
            self.ids_enviados.append(identificador)
        mensaje.update(
            {
                "from": REMITENTE_PRUEBA,
                "origin": ORIGEN_PRUEBA,
                "lamport": lamport,
                "sent_at": ahora_utc(),
                "body": CUERPO_PRUEBA,
                "seq": self._seq,
            }
        )
        if extra:
            mensaje.update(extra)
        return mensaje


def ahora_utc() -> str:
    """Fecha y hora UTC en ISO 8601 con milisegundos."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def llamar(ctx: Contexto, metodo: str, ruta: str, cuerpo: dict | None = None) -> Llamada:
    """Hace una llamada al grupo y nunca lanza: los errores quedan en la `Llamada`."""
    inicio = ctx.reloj()
    codigo: int | None = None
    texto = ""
    datos: object | None = None
    error: str | None = None
    agoto_espera = False
    try:
        respuesta = ctx.cliente.request(metodo, ruta, json=cuerpo)
        codigo = respuesta.status_code
        texto = respuesta.text
        try:
            datos = respuesta.json()
        except ValueError:
            datos = None
    except httpx.TimeoutException:
        agoto_espera = True
        error = f"sin respuesta en {ctx.timeout_s:g} s (tiempo de espera agotado)"
    except httpx.HTTPError as e:
        error = f"error de conexión: {type(e).__name__}: {e}"
    except Exception as e:  # salvaguarda 4: nada que responda el grupo tumba el script
        error = f"error inesperado: {type(e).__name__}: {e}"
    ms = round((ctx.reloj() - inicio) * 1000)
    llamada = Llamada(ctx.caso_actual, metodo, ruta, codigo, texto, datos, ms, error, agoto_espera)
    ctx.llamadas.append(llamada)
    return llamada


def leer_reloj(llamada: Llamada) -> tuple[int | None, str]:
    """El `lamport` de una respuesta de `/fed/health`, o el motivo por el que no hay."""
    if llamada.codigo is None:
        return None, f"no respondió: {llamada.error}"
    if not llamada.es_2xx:
        return None, f"respondió {llamada.codigo}, no 2xx"
    if not isinstance(llamada.datos, dict):
        return None, "el cuerpo no es un objeto JSON"
    if "lamport" not in llamada.datos:
        return None, "el cuerpo no trae lamport"
    valor = llamada.datos["lamport"]
    # 42.0 vale como 42, igual que en JSON Schema (A15); un booleano no es un número.
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        return None, f"lamport no es un entero >= 0: {json.dumps(valor, ensure_ascii=False)}"
    return valor, ""


def _resultado(
    ctx: Contexto,
    numero: int,
    nombre: str,
    severidad: str,
    estado: str,
    detalle: str,
    llamada: Llamada | None,
    enviado: str,
    esperado: str,
) -> Resultado:
    return Resultado(
        numero=numero,
        nombre=nombre,
        severidad=severidad,
        estado=estado,
        detalle=detalle,
        codigo_http=llamada.codigo if llamada else None,
        cuerpo=(llamada.texto if llamada.codigo is not None else llamada.error) if llamada else None,
        ms=llamada.ms if llamada else None,
        enviado=enviado,
        esperado=esperado,
    )


def _no_evaluado(numero: int, nombre: str, severidad: str, motivo: str, enviado: str, esperado: str) -> Resultado:
    return Resultado(numero, nombre, severidad, NO_EVALUADO, motivo, enviado=enviado, esperado=esperado)


def _aceptacion(ctx: Contexto, llamada: Llamada, que: str) -> tuple[bool, str]:
    """¿El grupo aceptó el mensaje como lo exige el central: 2xx dentro del tiempo de espera?"""
    if llamada.codigo is None:
        if llamada.agoto_espera:
            return False, (
                f"{llamada.error}: el central corta a los {ctx.timeout_s:g} s y reintenta "
                f"{que} sin fin"
            )
        return False, f"{llamada.error}: el central lo reintentaría sin fin"
    if not llamada.es_2xx:
        if llamada.es_4xx:
            return False, (
                f"respondió {llamada.codigo}: el central no reintenta un 4xx, así que el "
                f"grupo pierde {que}"
            )
        return False, f"respondió {llamada.codigo}: el central reintenta {que} sin fin"
    if not ctx.a_tiempo(llamada):
        return False, (
            f"respondió {llamada.codigo}, pero en {llamada.ms} ms: el central espera como "
            f"máximo {ctx.limite_ms} ms, lo cuenta como fallo y reintenta {que}"
        )
    return True, f"respondió {llamada.codigo} en {llamada.ms} ms"


# --- Casos -----------------------------------------------------------------------------


def caso_1(ctx: Contexto) -> Resultado:
    nombre = "GET /fed/health"
    enviado = f"GET {RUTA_SALUD}"
    esperado = "2xx con server (texto) y lamport (entero >= 0)"
    llamada = llamar(ctx, "GET", RUTA_SALUD)
    if llamada.codigo is None:
        ctx.sin_respuesta = True
        detalle = f"el servidor no respondió: {llamada.error}. Los demás casos no se ejecutaron"
        return _resultado(ctx, 1, nombre, OBLIGATORIO, FALLO, detalle, llamada, enviado, esperado)

    problemas: list[str] = []
    if not llamada.es_2xx:
        problemas.append(f"respondió {llamada.codigo}, no 2xx")
    datos = llamada.datos if isinstance(llamada.datos, dict) else None
    if llamada.es_2xx and datos is None:
        problemas.append("el cuerpo no es un objeto JSON")
    if datos is not None:
        servidor = datos.get("server")
        if isinstance(servidor, str) and servidor:
            ctx.server = servidor
        elif llamada.es_2xx:
            problemas.append("falta server o no es un texto")
    reloj, motivo = leer_reloj(llamada)
    if reloj is not None:
        ctx.lamport = reloj
    elif llamada.es_2xx and datos is not None:
        problemas.append(motivo)
    if llamada.es_2xx and not ctx.a_tiempo(llamada):
        problemas.append(
            f"tardó {llamada.ms} ms: el heartbeat del central espera como máximo "
            f"{ctx.limite_ms} ms y lo cuenta como fallo"
        )

    if problemas:
        detalle = "; ".join(problemas)
        if ctx.lamport is None:
            detalle += ". Sin un reloj entero, los casos 3, 5 y 7 no se evalúan"
        return _resultado(ctx, 1, nombre, OBLIGATORIO, FALLO, detalle, llamada, enviado, esperado)
    detalle = f"server={ctx.server}, lamport={ctx.lamport}"
    return _resultado(ctx, 1, nombre, OBLIGATORIO, PASO, detalle, llamada, enviado, esperado)


def _marca_caso_2(ctx: Contexto) -> int:
    base = ctx.lamport if ctx.lamport is not None else 0
    return min(base + 100, MAX_LAMPORT)


def caso_2(ctx: Contexto) -> Resultado:
    nombre = "POST /fed/messages con un mensaje nuevo"
    marca = _marca_caso_2(ctx)
    mensaje = ctx.nuevo_mensaje(marca)
    ctx.mensaje_caso_2 = mensaje
    origen_marca = "L + 100, con L el reloj del caso 1" if ctx.lamport is not None else "100, sin reloj del caso 1"
    enviado = f"POST {RUTA_MENSAJES} con id {mensaje['id']} y lamport {marca} ({origen_marca})"
    esperado = "2xx en menos de 3 s"
    llamada = llamar(ctx, "POST", RUTA_MENSAJES, mensaje)
    ctx.caso_2_aceptado = llamada.es_2xx
    aceptado, detalle = _aceptacion(ctx, llamada, "este mensaje")
    return _resultado(ctx, 2, nombre, OBLIGATORIO, PASO if aceptado else FALLO, detalle, llamada, enviado, esperado)


def caso_3(ctx: Contexto) -> Resultado:
    nombre = "Reloj después del mensaje nuevo"
    marca = _marca_caso_2(ctx)
    enviado = f"GET {RUTA_SALUD}"
    esperado = f"lamport >= {marca + 1}: aplicó max(local, {marca}) + 1"
    if ctx.lamport is None:
        return _no_evaluado(3, nombre, OBLIGATORIO, "el caso 1 no dio un reloj entero", enviado, esperado)
    if not ctx.caso_2_aceptado:
        return _no_evaluado(3, nombre, OBLIGATORIO, "el grupo no aceptó el mensaje del caso 2", enviado, esperado)
    llamada = llamar(ctx, "GET", RUTA_SALUD)
    reloj, motivo = leer_reloj(llamada)
    if reloj is None:
        return _resultado(ctx, 3, nombre, OBLIGATORIO, FALLO, f"no se pudo leer el reloj: {motivo}", llamada, enviado, esperado)
    ctx.reloj_tras_caso_2 = reloj
    if reloj >= marca + 1:
        detalle = f"el reloj pasó de {ctx.lamport} a {reloj}"
        return _resultado(ctx, 3, nombre, OBLIGATORIO, PASO, detalle, llamada, enviado, esperado)
    detalle = (
        f"el reloj quedó en {reloj} y debía ser al menos {marca + 1}: al recibir un mensaje "
        f"el grupo debe aplicar max(local, recibido) + 1 (sección 4)"
    )
    return _resultado(ctx, 3, nombre, OBLIGATORIO, FALLO, detalle, llamada, enviado, esperado)


def caso_4(ctx: Contexto) -> Resultado:
    nombre = "Duplicado: el mismo mensaje del caso 2"
    mensaje = ctx.mensaje_caso_2
    assert mensaje is not None, "el caso 2 siempre prepara su mensaje"
    enviado = f"POST {RUTA_MENSAJES} repitiendo el mensaje del caso 2 (id {mensaje['id']})"
    esperado = "2xx en menos de 3 s: un duplicado se descarta por id y se responde 2xx"
    llamada = llamar(ctx, "POST", RUTA_MENSAJES, mensaje)
    aceptado, detalle = _aceptacion(ctx, llamada, "el duplicado")
    return _resultado(ctx, 4, nombre, OBLIGATORIO, PASO if aceptado else FALLO, detalle, llamada, enviado, esperado)


def caso_5(ctx: Contexto) -> Resultado:
    nombre = "Reloj después del duplicado"
    enviado = f"GET {RUTA_SALUD}"
    esperado = "el mismo lamport que en el caso 3: el duplicado no tuvo efectos"
    if ctx.lamport is None:
        return _no_evaluado(5, nombre, ADVERTENCIA_SEVERIDAD, "el caso 1 no dio un reloj entero", enviado, esperado)
    if ctx.reloj_tras_caso_2 is None:
        return _no_evaluado(5, nombre, ADVERTENCIA_SEVERIDAD, "el caso 3 no midió el reloj", enviado, esperado)
    llamada = llamar(ctx, "GET", RUTA_SALUD)
    reloj, motivo = leer_reloj(llamada)
    if reloj is None:
        return _resultado(
            ctx, 5, nombre, ADVERTENCIA_SEVERIDAD, ADVERTENCIA, f"no se pudo leer el reloj: {motivo}", llamada, enviado, esperado
        )
    if reloj == ctx.reloj_tras_caso_2:
        return _resultado(ctx, 5, nombre, ADVERTENCIA_SEVERIDAD, PASO, f"el reloj sigue en {reloj}", llamada, enviado, esperado)
    detalle = (
        f"el reloj pasó de {ctx.reloj_tras_caso_2} a {reloj}: el duplicado pudo tener efectos, "
        f"o el grupo tuvo otra actividad entre las dos consultas"
    )
    return _resultado(ctx, 5, nombre, ADVERTENCIA_SEVERIDAD, ADVERTENCIA, detalle, llamada, enviado, esperado)


def caso_6(ctx: Contexto) -> Resultado:
    nombre = "Mensaje nuevo con campos desconocidos"
    mensaje = ctx.nuevo_mensaje(_marca_caso_2(ctx), extra=CAMPOS_DESCONOCIDOS)
    campos = ", ".join(CAMPOS_DESCONOCIDOS)
    enviado = f"POST {RUTA_MENSAJES} con id {mensaje['id']} y los campos extra {campos}"
    esperado = "2xx en menos de 3 s: los campos desconocidos se ignoran sin error"
    llamada = llamar(ctx, "POST", RUTA_MENSAJES, mensaje)
    aceptado, detalle = _aceptacion(ctx, llamada, "este mensaje")
    return _resultado(ctx, 6, nombre, OBLIGATORIO, PASO if aceptado else FALLO, detalle, llamada, enviado, esperado)


def caso_7(ctx: Contexto) -> Resultado:
    nombre = "Mensaje nuevo con marca menor que el reloj"
    enviado = f"GET {RUTA_SALUD}, POST {RUTA_MENSAJES} con lamport 1, GET {RUTA_SALUD}"
    esperado = "2xx en menos de 3 s (obligatorio) y el reloj sube exactamente 1 (advertencia)"
    if ctx.lamport is None:
        return _no_evaluado(7, nombre, OBLIGATORIO, "el caso 1 no dio un reloj entero", enviado, esperado)
    antes, motivo_antes = leer_reloj(llamar(ctx, "GET", RUTA_SALUD))
    mensaje = ctx.nuevo_mensaje(1)
    llamada = llamar(ctx, "POST", RUTA_MENSAJES, mensaje)
    aceptado, detalle = _aceptacion(ctx, llamada, "este mensaje")
    if not aceptado:
        return _resultado(ctx, 7, nombre, OBLIGATORIO, FALLO, detalle, llamada, enviado, esperado)
    despues, motivo_despues = leer_reloj(llamar(ctx, "GET", RUTA_SALUD))
    if antes is None or despues is None:
        motivo = motivo_antes or motivo_despues
        detalle += f"; no se pudo medir el reloj: {motivo}"
        return _resultado(ctx, 7, nombre, OBLIGATORIO, ADVERTENCIA, detalle, llamada, enviado, esperado)
    if despues == antes + 1:
        detalle += f"; el reloj pasó de {antes} a {despues}: max({antes}, 1) + 1"
        return _resultado(ctx, 7, nombre, OBLIGATORIO, PASO, detalle, llamada, enviado, esperado)
    detalle += (
        f"; el reloj pasó de {antes} a {despues} y se esperaba {antes + 1}, por "
        f"max({antes}, 1) + 1. Puede deberse a otra actividad del grupo entre las consultas"
    )
    return _resultado(ctx, 7, nombre, OBLIGATORIO, ADVERTENCIA, detalle, llamada, enviado, esperado)


def caso_8(ctx: Contexto) -> Resultado:
    nombre = "Mensaje sin id"
    mensaje = ctx.nuevo_mensaje(_marca_caso_2(ctx), con_id=False)
    enviado = f"POST {RUTA_MENSAJES} sin el campo id"
    esperado = "4xx: ni 2xx (lo aceptó) ni 5xx (se cayó). La sección 4 no lo exige"
    llamada = llamar(ctx, "POST", RUTA_MENSAJES, mensaje)
    if llamada.es_4xx:
        detalle = f"respondió {llamada.codigo}: rechazó el mensaje inválido"
        return _resultado(ctx, 8, nombre, ADVERTENCIA_SEVERIDAD, PASO, detalle, llamada, enviado, esperado)
    if llamada.codigo is None:
        detalle = f"{llamada.error}: un mensaje inválido no debería dejar sin respuesta al servidor"
    elif llamada.es_2xx:
        detalle = f"respondió {llamada.codigo}: aceptó un mensaje que no se puede deduplicar por id"
    elif llamada.codigo >= 500:
        detalle = f"respondió {llamada.codigo}: un mensaje inválido hizo fallar al servidor"
    else:
        detalle = f"respondió {llamada.codigo}, que no es 4xx"
    return _resultado(ctx, 8, nombre, ADVERTENCIA_SEVERIDAD, ADVERTENCIA, detalle, llamada, enviado, esperado)


def caso_9(ctx: Contexto) -> Resultado:
    nombre = "Tiempo de respuesta de cada llamada"
    medidas = [ll for ll in ctx.llamadas if ll.codigo is not None or ll.agoto_espera]
    enviado = f"ninguna llamada nueva: se revisan las {len(medidas)} llamadas de los casos 1 a 8"
    esperado = f"cada respuesta en menos de {ctx.timeout_s:g} s, el tiempo de espera del central"
    if not medidas:
        return _no_evaluado(9, nombre, OBLIGATORIO, "no hubo llamadas con respuesta para medir", enviado, esperado)
    lentas = [ll for ll in medidas if ll.agoto_espera or ll.ms > ctx.limite_ms]
    mas_lenta = max(medidas, key=lambda ll: ll.ms)
    if not lentas:
        detalle = f"la más lenta fue {mas_lenta.metodo} {mas_lenta.ruta} (caso {mas_lenta.caso}), con {mas_lenta.ms} ms"
        return Resultado(9, nombre, OBLIGATORIO, PASO, detalle, ms=mas_lenta.ms, enviado=enviado, esperado=esperado)
    partes = [
        f"{ll.metodo} {ll.ruta} (caso {ll.caso}): "
        + (ll.error if ll.agoto_espera else f"{ll.ms} ms")
        for ll in lentas
    ]
    detalle = (
        f"{len(lentas)} de {len(medidas)} llamadas superaron {ctx.limite_ms} ms: "
        + "; ".join(partes)
        + ". El central las cuenta como fallo y reintenta"
    )
    return Resultado(9, nombre, OBLIGATORIO, FALLO, detalle, ms=mas_lenta.ms, enviado=enviado, esperado=esperado)


CASOS: list[Callable[[Contexto], Resultado]] = [
    caso_1,
    caso_2,
    caso_3,
    caso_4,
    caso_5,
    caso_6,
    caso_7,
    caso_8,
    caso_9,
]

ETIQUETAS = {PASO: "PASA", FALLO: "FALLA", ADVERTENCIA: "ADVERTENCIA", NO_EVALUADO: "NO EVALUADO"}


def ejecutar(ctx: Contexto, progreso: Callable[[str], None] = lambda _: None) -> list[Resultado]:
    """Corre los casos en orden. Si el grupo no responde al caso 1, para ahí."""
    resultados: list[Resultado] = []
    for numero, caso in enumerate(CASOS, start=1):
        ctx.caso_actual = numero
        try:
            resultado = caso(ctx)
        except Exception as e:  # un error del script no se le atribuye al grupo
            resultado = Resultado(
                numero,
                caso.__name__,
                OBLIGATORIO,
                NO_EVALUADO,
                f"error interno del script: {type(e).__name__}: {e}",
            )
        resultados.append(resultado)
        progreso(f"Caso {numero}/{len(CASOS)} · {resultado.nombre}: {ETIQUETAS[resultado.estado]}")
        if ctx.sin_respuesta:
            progreso("El servidor no respondió al caso 1: no se ejecutan los demás casos")
            break
    return resultados
