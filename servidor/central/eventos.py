"""Eventos del log, una línea por evento (CS-002 §8).

Formato: `2026-11-15T14:03:22.104Z central EVENTO clave=valor …`. Los valores con
espacios, `=`, `"` o vacíos van entre comillas, como texto JSON; `None` se omite.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from enum import StrEnum

registro = logging.getLogger("central.eventos")


class Evento(StrEnum):
    ARRANQUE = "ARRANQUE"
    PARADA = "PARADA"
    REGISTRADO = "REGISTRADO"
    RENOVADO = "RENOVADO"
    REGISTRO_RECHAZADO = "REGISTRO_RECHAZADO"
    RECIBIDO = "RECIBIDO"
    DUPLICADO_DESCARTADO = "DUPLICADO_DESCARTADO"
    RECHAZADO_400 = "RECHAZADO_400"
    REENVIADO = "REENVIADO"
    REINTENTO = "REINTENTO"
    RECHAZADO_4XX = "RECHAZADO_4XX"
    GRUPO_CAIDO = "GRUPO_CAIDO"
    GRUPO_VOLVIO = "GRUPO_VOLVIO"
    HISTORIAL_SERVIDO = "HISTORIAL_SERVIDO"
    ADMIN = "ADMIN"


def ahora_iso(momento: datetime | None = None) -> str:
    """Fecha ISO 8601 en UTC con milisegundos: `2026-11-15T14:03:22.104Z`."""
    momento = momento or datetime.now(UTC)
    return momento.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{momento.microsecond // 1000:03d}Z"


def _valor(valor: object) -> str:
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, float):
        valor = f"{valor:.3f}".rstrip("0").rstrip(".")
    texto = str(valor)
    if texto == "" or any(c.isspace() or c in '="' for c in texto) or not texto.isprintable():
        return json.dumps(texto, ensure_ascii=False)
    return texto


def formatear(evento: Evento, datos: dict[str, object], momento: datetime | None = None) -> str:
    partes = [ahora_iso(momento), "central", str(evento)]
    partes += [f"{clave}={_valor(valor)}" for clave, valor in datos.items() if valor is not None]
    return " ".join(partes)


def registrar(evento: Evento, **datos: object) -> None:
    registro.info(formatear(evento, datos), extra={"evento": evento, "datos": datos})


def configurar_log() -> None:
    """Los eventos van a la salida estándar tal cual; el resto de Python, a la de errores."""
    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(logging.Formatter("%(message)s"))
    registro.addHandler(manejador)
    registro.setLevel(logging.INFO)
    registro.propagate = False
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
