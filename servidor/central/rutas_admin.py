"""Rutas del auxiliar, protegidas con ADMIN_TOKEN (D17, CS-002 §3.6).

Sin token configurado, todas responden 403. El token se compara en tiempo constante y
nunca se escribe en el log (salvaguarda 8).
"""

import asyncio
import hmac
from typing import Any

from fastapi import APIRouter, Depends, Request

from .errores import ErrorHttp
from .eventos import Evento, registrar


def verificar_token(request: Request) -> None:
    config = request.app.state.config
    if not config.administracion_habilitada:
        raise ErrorHttp(403, "administración deshabilitada: ADMIN_TOKEN no está configurado")
    esquema, _, token = request.headers.get("authorization", "").partition(" ")
    valido = esquema.lower() == "bearer" and hmac.compare_digest(
        token.strip().encode(), config.admin_token.encode()
    )
    if not valido:
        registrar(Evento.ADMIN, accion="token_rechazado", ruta=request.url.path)
        raise ErrorHttp(401, "token ausente o incorrecto")


router = APIRouter(prefix="/admin", dependencies=[Depends(verificar_token)])


@router.delete("/servers/{server}")
async def quitar_servidor(server: str, request: Request) -> dict[str, Any]:
    estado = request.app.state
    if not await asyncio.to_thread(estado.almacen.quitar_servidor, server):
        raise ErrorHttp(404, "servidor no registrado", [{
            "field": "server", "problem": f"no hay un servidor registrado con el nombre {server[:64]}",
        }])
    await estado.repartidor.sincronizar()
    registrar(Evento.ADMIN, accion="quitar", server=server)
    return {"removed": server}


@router.post("/reset")
async def reiniciar_historial(request: Request) -> dict[str, Any]:
    estado = request.app.state
    borrados = await asyncio.to_thread(estado.almacen.borrar_historial)
    ultimo = await asyncio.to_thread(estado.almacen.ultimo_seq)
    registrar(Evento.ADMIN, accion="reiniciar", borrados=borrados, ultimo_seq=ultimo)
    return {"deleted": borrados, "last_seq": ultimo}
