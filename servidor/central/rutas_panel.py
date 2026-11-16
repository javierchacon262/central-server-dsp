"""Panel de observación y estado público: GET / y GET /servers (D17, CS-002 §3.5)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

PANEL = (Path(__file__).parent / "panel.html").read_text(encoding="utf-8")

# El panel no carga nada de fuera y solo habla con el propio central (salvaguarda 9).
CABECERAS_PANEL = {
    "content-security-policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cache-control": "no-cache",
}


@router.get("/", response_class=HTMLResponse)
async def panel() -> HTMLResponse:
    return HTMLResponse(PANEL, headers=CABECERAS_PANEL)


def _fecha(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto)
    except ValueError:
        return None


@router.get("/servers")
async def estado_servidores(request: Request) -> dict[str, Any]:
    estado = request.app.state
    servidores = await asyncio.to_thread(estado.almacen.listar_servidores)
    ultimo = await asyncio.to_thread(estado.almacen.ultimo_seq)
    ahora = datetime.now(UTC)
    salida = []
    for s in servidores:
        push = s.modo == "push"
        if push:
            # En push decide el heartbeat (D15); recién registrado se asume vivo.
            latido = estado.repartidor.estado(s.nombre)
            vivo = latido is None or latido.vivo
        else:
            # En pull, una consulta con `server` o un registro en los últimos 60 s (A3).
            visto = _fecha(s.visto_en)
            vivo = visto is not None and (ahora - visto).total_seconds() <= estado.config.ventana_pull_s
        salida.append({
            "server": s.nombre,
            "mode": s.modo,
            "url": s.url,
            "state": "up" if vivo else "down",
            "registered_at": s.registrado_en,
            "last_seen": s.visto_en,
            "lamport": s.lamport if push else None,
            "delivered_seq": s.entregado_seq if push else None,
            "pending": s.pendientes if push else None,
        })
    return {"last_seq": ultimo, "servers": salida}
