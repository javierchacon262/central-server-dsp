"""Errores con la forma única `{"error", "detail": [{"field", "problem"}]}` (D12).

FastAPI responde `422` por defecto; aquí todo error de validación es `400`, con un
problema en español por campo. Un error del cliente nunca responde `5xx`
(salvaguarda 11).
"""

import json
import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .modelo import LAMPORT_MAXIMO

registro = logging.getLogger("central")

PROBLEMAS = {
    "id": "obligatorio: texto de 1 a 100 caracteres",
    "from": "obligatorio: texto de 1 a 100 caracteres",
    "origin": "obligatorio: texto de 1 a 32 caracteres",
    "lamport": "debe ser un entero ≥ 0",
    "sent_at": "opcional, pero si viene debe ser texto de hasta 64 caracteres",
    "body": "opcional, pero si viene debe ser texto de hasta 10000 caracteres",
    "server": "obligatorio: de 1 a 32 letras ASCII, dígitos, _ o -",
    "mode": 'debe ser "push" o "pull"',
    "url": "obligatoria en modo push: URL absoluta http o https",
    "since": f"debe ser un entero de 0 a {LAMPORT_MAXIMO}",
    "after_seq": f"debe ser un entero de 0 a {LAMPORT_MAXIMO}",
    "limit": "debe ser un entero de 1 a 1000",
}

TITULOS = {
    "/messages": "mensaje inválido",
    "/register": "registro inválido",
    "/history": "parámetros inválidos",
}


class ErrorHttp(Exception):
    """Error que se responde tal cual, con la forma de la especificación."""

    def __init__(self, codigo: int, error: str, detalle: list[dict[str, str]] | None = None) -> None:
        self.codigo = codigo
        self.error = error
        self.detalle = detalle or []
        super().__init__(error)


def respuesta_error(codigo: int, error: str, detalle: list[dict[str, str]] | None = None) -> JSONResponse:
    return JSONResponse(status_code=codigo, content={"error": error, "detail": detalle or []})


def _problema(campo: str, error: dict[str, Any]) -> str:
    if campo == "lamport" and error.get("type") == "less_than_equal":
        return f"no puede ser mayor que {LAMPORT_MAXIMO} (2⁵³ − 1)"
    if campo == "url" and error.get("type") == "value_error":
        return str(error.get("ctx", {}).get("error", PROBLEMAS["url"]))
    return PROBLEMAS.get(campo, str(error.get("msg", "valor inválido")))


def detalle_de(errores: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Un problema por campo, en el orden en que pydantic los encontró."""
    detalle: list[dict[str, str]] = []
    vistos: set[str] = set()
    for error in errores:
        loc = [p for p in error.get("loc", ()) if p not in ("body", "query", "path")]
        if not loc:
            continue
        campo = str(loc[0])
        if campo in vistos:
            continue
        vistos.add(campo)
        detalle.append({"field": campo, "problem": _problema(campo, error)})
    return detalle


def resumen(detalle: list[dict[str, str]]) -> str:
    """Motivo de una línea para el log."""
    return "; ".join(f"{d['field']}: {d['problem']}" for d in detalle)


async def leer_objeto_json(request: Request) -> dict[str, Any]:
    """Lee el cuerpo como JSON sin mirar el Content-Type: tolerante al recibir (CS-002 §1)."""
    crudo = await request.body()
    try:
        datos = json.loads(crudo)
    except (ValueError, UnicodeDecodeError):
        raise ErrorHttp(400, "JSON mal formado") from None
    if not isinstance(datos, dict):
        raise ErrorHttp(400, "el cuerpo debe ser un objeto JSON")
    return datos


def validar(modelo: type, datos: dict[str, Any], titulo: str):
    try:
        return modelo.model_validate(datos)
    except ValidationError as e:
        raise ErrorHttp(400, titulo, detalle_de(e.errors(include_url=False))) from None


async def manejar_error_http(_: Request, exc: ErrorHttp) -> JSONResponse:
    return respuesta_error(exc.codigo, exc.error, exc.detalle)


async def manejar_validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
    titulo = TITULOS.get(request.url.path, "solicitud inválida")
    return respuesta_error(400, titulo, detalle_de(list(exc.errors())))


async def manejar_starlette(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    mensajes = {404: "ruta no encontrada", 405: "método no permitido"}
    return respuesta_error(exc.status_code, mensajes.get(exc.status_code, str(exc.detail)))


async def manejar_inesperado(request: Request, exc: Exception) -> JSONResponse:
    registro.exception("error interno en %s %s", request.method, request.url.path)
    return respuesta_error(500, "error interno del central")
