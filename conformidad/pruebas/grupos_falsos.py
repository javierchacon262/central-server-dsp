"""Grupos falsos para probar el script (CS-004, O2 y O3).

- `GrupoConforme` cumple la sección 4: aplica `max(local, recibido) + 1`, descarta
  duplicados por `id` con `2xx`, ignora los campos desconocidos y rechaza con `400` un
  mensaje sin `id`.
- `GrupoConErrores` tiene tres errores conocidos: no actualiza el reloj, responde `500`
  al duplicado y tarda 4 s con el mensaje de campos desconocidos. El script debe fallar
  los casos 3, 4, 6 y 9.

La misma lógica sirve sobre `httpx.MockTransport`, con un reloj falso que avanza el
retraso sin dormir, y como servidor HTTP real para la prueba de punta a punta:

    python -m pruebas.grupos_falsos conforme 18081
    python -m pruebas.grupos_falsos errores 18082
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx

CAMPOS_SECCION_4 = {"id", "from", "origin", "lamport", "sent_at", "body", "seq"}

Respuesta = tuple[int, object, float]  # código, cuerpo JSON y retraso en segundos


class GrupoFalso:
    nombre = "gfalso"

    def __init__(self, lamport_inicial: int = 7) -> None:
        self.lamport = lamport_inicial
        self.ids: set[str] = set()
        self.recibidos: list[dict] = []
        self._candado = threading.Lock()

    def atender(self, metodo: str, ruta: str, cuerpo: bytes) -> Respuesta:
        with self._candado:
            if metodo == "GET" and ruta == "/fed/health":
                return 200, {"server": self.nombre, "lamport": self.lamport}, 0.0
            if metodo == "POST" and ruta == "/fed/messages":
                try:
                    mensaje = json.loads(cuerpo)
                except ValueError:
                    return 400, {"error": "JSON inválido"}, 0.0
                if not isinstance(mensaje, dict):
                    return 400, {"error": "se esperaba un objeto"}, 0.0
                self.recibidos.append(mensaje)
                return self.recibir(mensaje)
            return 404, {"error": "ruta desconocida"}, 0.0

    def recibir(self, mensaje: dict) -> Respuesta:
        raise NotImplementedError


def _sin_id_o_marca(mensaje: dict) -> Respuesta | None:
    if not isinstance(mensaje.get("id"), str) or not mensaje["id"]:
        return 400, {"error": "mensaje inválido", "detail": [{"field": "id", "problem": "obligatorio"}]}, 0.0
    lamport = mensaje.get("lamport")
    if isinstance(lamport, bool) or not isinstance(lamport, int) or lamport < 0:
        return 400, {"error": "mensaje inválido", "detail": [{"field": "lamport", "problem": "entero >= 0"}]}, 0.0
    return None


class GrupoConforme(GrupoFalso):
    nombre = "gconforme"

    def recibir(self, mensaje: dict) -> Respuesta:
        if (error := _sin_id_o_marca(mensaje)) is not None:
            return error
        if mensaje["id"] in self.ids:
            return 200, {"status": "duplicate"}, 0.0
        self.ids.add(mensaje["id"])
        self.lamport = max(self.lamport, mensaje["lamport"]) + 1
        return 200, {"status": "ok"}, 0.0


class GrupoConErrores(GrupoFalso):
    nombre = "gerrores"
    retraso_campos_desconocidos = 4.0

    def recibir(self, mensaje: dict) -> Respuesta:
        if (error := _sin_id_o_marca(mensaje)) is not None:
            return error
        if mensaje["id"] in self.ids:
            # Error 2: un duplicado tumba el servidor en lugar de descartarse.
            return 500, {"error": "UNIQUE constraint failed: mensajes.id"}, 0.0
        self.ids.add(mensaje["id"])
        # Error 1: no aplica max(local, recibido) + 1, el reloj nunca se mueve.
        # Error 3: los campos desconocidos lo vuelven lento.
        retraso = self.retraso_campos_desconocidos if set(mensaje) - CAMPOS_SECCION_4 else 0.0
        return 200, {"status": "ok"}, retraso


class RelojFalso:
    """Reloj monótono que avanza el retraso de cada respuesta sin dormir."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def transporte(grupo: GrupoFalso, reloj: RelojFalso | None = None, paso_s: float = 0.004) -> httpx.MockTransport:
    """`MockTransport` que atiende con el grupo y anota cada petición en `grupo.peticiones`."""
    grupo.peticiones = []  # type: ignore[attr-defined]

    def manejar(peticion: httpx.Request) -> httpx.Response:
        grupo.peticiones.append(peticion)  # type: ignore[attr-defined]
        codigo, datos, retraso = grupo.atender(peticion.method, peticion.url.path, peticion.content)
        if reloj is not None:
            reloj.t += retraso + paso_s
        return httpx.Response(codigo, json=datos)

    return httpx.MockTransport(manejar)


def servir(grupo: GrupoFalso, puerto: int, anfitrion: str = "0.0.0.0") -> None:
    """Levanta el grupo como servidor HTTP real, para la prueba de punta a punta."""

    class Manejador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _atender(self, metodo: str) -> None:
            largo = int(self.headers.get("Content-Length") or 0)
            cuerpo = self.rfile.read(largo) if largo else b""
            codigo, datos, retraso = grupo.atender(metodo, urlsplit(self.path).path, cuerpo)
            if retraso:
                time.sleep(retraso)
            contenido = json.dumps(datos).encode()
            try:
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(contenido)))
                self.end_headers()
                self.wfile.write(contenido)
            except (BrokenPipeError, ConnectionResetError):
                pass  # el cliente ya cortó por tiempo de espera

        def do_GET(self) -> None:  # noqa: N802 (nombre que exige http.server)
            self._atender("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._atender("POST")

        def log_message(self, formato: str, *args: object) -> None:
            sys.stderr.write(f"{grupo.nombre} {self.address_string()} {formato % args}\n")

    servidor = ThreadingHTTPServer((anfitrion, puerto), Manejador)
    print(f"{grupo.nombre} escuchando en {anfitrion}:{puerto}", file=sys.stderr, flush=True)
    servidor.serve_forever()


GRUPOS = {"conforme": GrupoConforme, "errores": GrupoConErrores}

if __name__ == "__main__":
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in GRUPOS:
        print("uso: python -m pruebas.grupos_falsos conforme|errores [puerto]", file=sys.stderr)
        sys.exit(2)
    servir(GRUPOS[sys.argv[1]](), int(sys.argv[2]) if len(sys.argv) == 3 else 8000)
