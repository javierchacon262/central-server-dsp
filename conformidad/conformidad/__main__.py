"""Punto de entrada: `python -m conformidad URL [--timeout S]`.

El progreso va a la salida de error y el informe a la salida estándar, así que
`... > conformidad.txt` deja solo el informe. Códigos de salida: 0 si pasan todos los
casos obligatorios, 1 si falla alguno y 2 si la URL es inválida o el servidor no
responde al primer caso.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from typing import TextIO
from urllib.parse import urlsplit

import httpx

from . import VERSION_ESPECIFICACION, VERSION_SCRIPT
from .casos import Contexto, ejecutar
from .informe import codigo_salida, formatear

SALIDA_URL_INVALIDA = 2


def normalizar_url(texto: str) -> str:
    """URL absoluta http o https, sin `/` final. `ValueError` con el motivo."""
    texto = texto.strip()
    partes = urlsplit(texto)
    if partes.scheme not in ("http", "https"):
        raise ValueError("debe empezar con http:// o https://")
    if not partes.hostname:
        raise ValueError("falta el nombre o la dirección del servidor")
    try:
        partes.port
    except ValueError:
        raise ValueError("el puerto no es un número válido") from None
    if partes.query or partes.fragment:
        raise ValueError("no debe llevar ? ni #: es la URL base del servidor, sin /fed/...")
    return texto.rstrip("/")


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="conformidad",
        description=(
            "Prueba GET /fed/health y POST /fed/messages del servidor de un grupo "
            f"(especificación {VERSION_ESPECIFICACION}). El informe va a la salida estándar."
        ),
    )
    parser.add_argument(
        "url",
        help="URL base del servidor del grupo, por ejemplo http://localhost:8000",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="tiempo de espera por llamada, en segundos (por defecto 3, el del central)",
    )
    parser.add_argument("--version", action="version", version=f"conformidad {VERSION_SCRIPT}")
    return parser.parse_args(argv)


def principal(
    argv: list[str] | None = None,
    *,
    transporte: httpx.BaseTransport | None = None,
    reloj: Callable[[], float] = time.monotonic,
    salida: TextIO | None = None,
    errores: TextIO | None = None,
) -> int:
    salida = salida or sys.stdout
    errores = errores or sys.stderr
    args = _argumentos(argv)

    try:
        url = normalizar_url(args.url)
    except ValueError as e:
        print(f"URL inválida ({args.url!r}): {e}", file=errores)
        return SALIDA_URL_INVALIDA
    if not args.timeout > 0:
        print("--timeout debe ser mayor que 0", file=errores)
        return SALIDA_URL_INVALIDA

    print(f"Probando {url} (especificación {VERSION_ESPECIFICACION}, script {VERSION_SCRIPT})", file=errores)
    # Salvaguarda 1: solo se llama a la URL dada; sin proxies del entorno ni redirecciones.
    with httpx.Client(
        base_url=url,
        timeout=args.timeout,
        follow_redirects=False,
        trust_env=False,
        transport=transporte,
        headers={"User-Agent": f"conformidad-dsp/{VERSION_SCRIPT}"},
    ) as cliente:
        ctx = Contexto(url=url, cliente=cliente, timeout_s=args.timeout, reloj=reloj)
        resultados = ejecutar(ctx, progreso=lambda linea: print(linea, file=errores, flush=True))

    print(formatear(resultados, ctx), file=salida, end="")
    codigo = codigo_salida(resultados, ctx)
    print(f"Código de salida: {codigo}", file=errores)
    return codigo


if __name__ == "__main__":
    sys.exit(principal())
