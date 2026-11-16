"""Rutas que llaman los grupos: /register, /messages, /history y /health (CS-002 §3.1–3.4)."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from .almacen import TopeDeServidores
from .errores import ErrorHttp, leer_objeto_json, resumen, validar
from .eventos import Evento, ahora_iso, registrar
from .modelo import LAMPORT_MAXIMO, SPEC_VERSION, Mensaje, Registro
from .urls import motivo_destino_prohibido

router = APIRouter()


def _texto_para_log(datos: Any, campo: str, largo: int = 64) -> str | None:
    valor = datos.get(campo) if isinstance(datos, dict) else None
    return valor[:largo] if isinstance(valor, str) else None


@router.post("/register")
async def registrar_servidor(request: Request) -> dict[str, Any]:
    estado = request.app.state
    datos: Any = None
    try:
        datos = await leer_objeto_json(request)
        registro = validar(Registro, datos, "registro inválido")
        if registro.mode == "push":
            motivo = await motivo_destino_prohibido(registro.url, estado.config.permitir_url_privadas)
            if motivo:
                raise ErrorHttp(400, "registro inválido", [{"field": "url", "problem": motivo}])
        try:
            servidor, nuevo = await asyncio.to_thread(
                estado.almacen.registrar_servidor, registro, ahora_iso(), estado.config.max_servidores
            )
        except TopeDeServidores:
            raise ErrorHttp(400, "registro inválido", [{
                "field": "server",
                "problem": f"ya hay {estado.config.max_servidores} servidores registrados; "
                           "pídele al auxiliar que libere uno",
            }]) from None
    except ErrorHttp as e:
        registrar(Evento.REGISTRO_RECHAZADO, server=_texto_para_log(datos, "server"),
                  motivo=resumen(e.detalle) or e.error)
        raise
    registrar(Evento.REGISTRADO if nuevo else Evento.RENOVADO,
              server=servidor.nombre, mode=servidor.modo, url=servidor.url)
    await estado.repartidor.sincronizar()
    estado.repartidor.latir_ya(servidor.nombre)
    return {"server": servidor.nombre, "url": servidor.url, "mode": servidor.modo, "new": nuevo}


@router.post("/messages")
async def recibir_mensaje(request: Request) -> dict[str, Any]:
    estado = request.app.state
    datos: Any = None
    try:
        datos = await leer_objeto_json(request)
        mensaje = validar(Mensaje, datos, "mensaje inválido")
    except ErrorHttp as e:
        registrar(Evento.RECHAZADO_400, origin=_texto_para_log(datos, "origin", 32),
                  motivo=resumen(e.detalle) or e.error)
        raise
    seq, nuevo, distinto = await asyncio.to_thread(estado.almacen.guardar_mensaje, mensaje, ahora_iso())
    if nuevo:
        registrar(Evento.RECIBIDO, id=mensaje.id, lamport=mensaje.lamport, origin=mensaje.origin,
                  **{"from": mensaje.from_}, seq=seq)
        estado.repartidor.avisar()
    else:
        # Si el contenido difiere, gana el primero y queda en el log (A4).
        registrar(Evento.DUPLICADO_DESCARTADO, id=mensaje.id, origin=mensaje.origin,
                  distinto=True if distinto else None)
    return {"id": mensaje.id, "seq": seq, "duplicate": not nuevo}


EnteroDeMarca = Annotated[int | None, Query(ge=0, le=LAMPORT_MAXIMO)]


@router.get("/history")
async def leer_historial(
    request: Request,
    since: EnteroDeMarca = None,
    after_seq: EnteroDeMarca = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 1000,
    server: str | None = None,
) -> JSONResponse:
    estado = request.app.state
    if since is not None and after_seq is not None:
        raise ErrorHttp(400, "parámetros inválidos",
                        [{"field": "after_seq", "problem": "no se puede combinar con since"}])
    if server:
        # Señal de vida en pull (A3). Un nombre no registrado se ignora (A16).
        await asyncio.to_thread(estado.almacen.marcar_visto, server, ahora_iso())
    if after_seq is not None:
        mensajes = await asyncio.to_thread(estado.almacen.historial_despues_de_seq, after_seq, limit)
    else:
        since = since or 0
        mensajes = await asyncio.to_thread(estado.almacen.historial_desde_lamport, since, limit)
    if mensajes:
        registrar(Evento.HISTORIAL_SERVIDO, server=server[:32] if server else None,
                  since=since, after_seq=after_seq, n=len(mensajes))
    return JSONResponse([m.como_json() for m in mensajes])


@router.get("/health")
async def salud(request: Request) -> dict[str, Any]:
    # Sin red y sin escrituras (salvaguarda 10).
    ultimo = await asyncio.to_thread(request.app.state.almacen.ultimo_seq)
    return {"status": "ok", "spec_version": SPEC_VERSION, "last_seq": ultimo}
