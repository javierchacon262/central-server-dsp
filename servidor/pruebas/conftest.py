"""App con almacén temporal, cliente de prueba y grupos falsos sobre httpx.MockTransport."""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from central.configuracion import Configuracion
from central.principal import crear_app

TOKEN = "token-de-prueba-0123456789"


class GruposFalsos:
    """Servidores de grupo simulados. Cada grupo es un host: `http://g1.prueba`, …

    - `codigos_mensajes[host]`: cola de respuestas para `/fed/messages` (por defecto 200);
      un elemento puede ser un código o `"timeout"`.
    - `salud[host]`: código de `/fed/health` (por defecto 200) o `"timeout"`.
    - `retraso[host]`: segundos que tarda `/fed/messages`.
    """

    def __init__(self) -> None:
        self.recibidos: dict[str, list[dict]] = defaultdict(list)
        self.intentos: dict[str, list[dict]] = defaultdict(list)
        self.codigos_mensajes: dict[str, list] = defaultdict(list)
        self.salud: dict[str, object] = {}
        self.lamport: dict[str, int] = {}
        self.retraso: dict[str, float] = {}
        self.consultas_salud: dict[str, int] = defaultdict(int)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if request.url.path.endswith("/fed/health"):
            self.consultas_salud[host] += 1
            codigo = self.salud.get(host, 200)
            if codigo == "timeout":
                raise httpx.ReadTimeout("sin respuesta", request=request)
            return httpx.Response(codigo, json={"server": host.split(".")[0],
                                                "lamport": self.lamport.get(host, 0)})
        if request.url.path.endswith("/fed/messages"):
            if self.retraso.get(host):
                await asyncio.sleep(self.retraso[host])
            cuerpo = json.loads(request.content)
            self.intentos[host].append(cuerpo)
            cola = self.codigos_mensajes[host]
            codigo = cola.pop(0) if cola else 200
            if codigo == "timeout":
                raise httpx.ReadTimeout("sin respuesta", request=request)
            if 200 <= codigo < 300:
                self.recibidos[host].append(cuerpo)
            return httpx.Response(codigo, json={"ok": 200 <= codigo < 300})
        return httpx.Response(404, json={"error": "no existe"})


@pytest.fixture
def config(tmp_path) -> Configuracion:
    return Configuracion(
        admin_token=TOKEN,
        ruta_bd=str(tmp_path / "central.db"),
        heartbeat_intervalo_s=0.05,
        heartbeat_fallos_para_caido=3,
        backoff_base_s=0.02,
        backoff_max_s=0.1,
        http_timeout_s=0.5,
        permitir_url_privadas=True,
    )


@pytest.fixture
def grupos() -> GruposFalsos:
    return GruposFalsos()


@pytest.fixture
def crear_cliente(config, grupos):
    def crear(**cambios) -> TestClient:
        return TestClient(crear_app(replace(config, **cambios), transporte=httpx.MockTransport(grupos)))

    return crear


@pytest.fixture
def cliente(crear_cliente):
    with crear_cliente() as c:
        yield c


@pytest.fixture
def eventos(caplog):
    caplog.set_level(logging.INFO, logger="central.eventos")
    return caplog


def esperar(condicion, tiempo: float = 3.0, mensaje: str = "la condición no se cumplió") -> None:
    limite = time.monotonic() + tiempo
    while time.monotonic() < limite:
        if condicion():
            return
        time.sleep(0.01)
    assert condicion(), mensaje


def mensaje(**cambios) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "from": "ana@g3",
        "origin": "g3",
        "lamport": 42,
        "sent_at": "2026-11-10T14:03:22Z",
        "body": "¿Ya subieron el compose?",
    }
    base.update(cambios)
    return base


def servidor(cliente: TestClient, nombre: str) -> dict:
    return next(s for s in cliente.get("/servers").json()["servers"] if s["server"] == nombre)
