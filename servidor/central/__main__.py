"""Arranque: `python -m central`."""

import sys

import uvicorn

from .configuracion import Configuracion, ErrorDeConfiguracion
from .eventos import configurar_log
from .principal import crear_app


def main() -> int:
    try:
        config = Configuracion.desde_entorno()
    except ErrorDeConfiguracion as e:
        print("El central no arranca porque la configuración tiene problemas:", file=sys.stderr)
        for problema in e.problemas:
            print(f"  - {problema}", file=sys.stderr)
        print("Corrige esas variables de entorno (ver .env.example) y vuelve a arrancar.", file=sys.stderr)
        return 2
    configurar_log()
    uvicorn.run(
        crear_app(config),
        host="0.0.0.0",
        port=config.puerto,
        access_log=False,  # el log del central son sus eventos (CS-002 §8)
        log_level="warning",
        server_header=False,
        timeout_graceful_shutdown=5,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
