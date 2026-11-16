"""Construcción de la app y su ciclo de vida."""

import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import errores
from .almacen import Almacen
from .configuracion import Configuracion
from .eventos import Evento, registrar
from .modelo import SPEC_VERSION
from .reenvio import Repartidor
from .rutas_admin import router as rutas_admin
from .rutas_grupos import router as rutas_grupos
from .rutas_panel import router as rutas_panel


def crear_app(
    config: Configuracion,
    almacen: Almacen | None = None,
    transporte: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """`transporte` reemplaza la red en las pruebas (httpx.MockTransport)."""
    almacen = almacen or Almacen(config.ruta_bd)

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        await asyncio.to_thread(almacen.inicializar)
        http = httpx.AsyncClient(
            transport=transporte,
            timeout=config.http_timeout_s,
            follow_redirects=False,  # una redirección no lleva a una dirección prohibida (A2)
            trust_env=False,
            headers={"user-agent": f"central-dsp/{SPEC_VERSION}"},
        )
        repartidor = Repartidor(config, almacen, http)
        app.state.config = config
        app.state.almacen = almacen
        app.state.repartidor = repartidor
        mensajes, servidores = await asyncio.to_thread(almacen.contar)
        registrar(
            Evento.ARRANQUE,
            mensajes=mensajes,
            servidores=servidores,
            ultimo_seq=await asyncio.to_thread(almacen.ultimo_seq),
            spec_version=SPEC_VERSION,
            administracion="habilitada" if config.administracion_habilitada else "deshabilitada",
            url_privadas="permitidas" if config.permitir_url_privadas else "rechazadas",
        )
        await repartidor.sincronizar()
        try:
            yield
        finally:
            await repartidor.detener()
            await http.aclose()
            mensajes, servidores = await asyncio.to_thread(almacen.contar)
            registrar(Evento.PARADA, mensajes=mensajes, servidores=servidores,
                      ultimo_seq=await asyncio.to_thread(almacen.ultimo_seq))

    app = FastAPI(
        title="Servidor central · chat distribuido",
        version=SPEC_VERSION,
        lifespan=ciclo_de_vida,
        # La especificación pública es la de especificacion/, no la que genera FastAPI.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_exception_handler(errores.ErrorHttp, errores.manejar_error_http)
    app.add_exception_handler(RequestValidationError, errores.manejar_validacion)
    app.add_exception_handler(StarletteHTTPException, errores.manejar_starlette)
    app.add_exception_handler(Exception, errores.manejar_inesperado)
    app.include_router(rutas_grupos)
    app.include_router(rutas_panel)
    app.include_router(rutas_admin)
    return app
