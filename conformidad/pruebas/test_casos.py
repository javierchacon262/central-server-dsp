"""Cada caso contra los dos grupos falsos y contra respuestas inesperadas (CS-004, O2)."""

from __future__ import annotations

import json

import httpx
import pytest

from conformidad.casos import (
    ADVERTENCIA,
    CUERPO_PRUEBA,
    FALLO,
    NO_EVALUADO,
    ORIGEN_PRUEBA,
    PASO,
    Contexto,
    ejecutar,
)
from conformidad.informe import codigo_salida
from pruebas.grupos_falsos import GrupoConErrores, GrupoConforme, RelojFalso, transporte

URL = "http://grupo.prueba:8000"


def correr(manejador_o_transporte, reloj=None, url: str = URL):
    if isinstance(manejador_o_transporte, httpx.BaseTransport):
        trans = manejador_o_transporte
    else:
        trans = httpx.MockTransport(manejador_o_transporte)
    reloj = reloj or RelojFalso()
    with httpx.Client(base_url=url, transport=trans, timeout=3.0, follow_redirects=False) as cliente:
        ctx = Contexto(url=url, cliente=cliente, timeout_s=3.0, reloj=reloj)
        resultados = ejecutar(ctx)
    return ctx, resultados


def estados(resultados):
    return {r.numero: r.estado for r in resultados}


def test_grupo_conforme_pasa_todos_los_casos():
    grupo = GrupoConforme(lamport_inicial=7)
    ctx, resultados = correr(transporte(grupo, reloj := RelojFalso()), reloj)

    assert [r.numero for r in resultados] == list(range(1, 10))
    assert estados(resultados) == {n: PASO for n in range(1, 10)}
    assert codigo_salida(resultados, ctx) == 0
    assert ctx.server == "gconforme"
    assert ctx.lamport == 7


def test_grupo_con_errores_falla_3_4_6_y_9():
    grupo = GrupoConErrores(lamport_inicial=7)
    ctx, resultados = correr(transporte(grupo, reloj := RelojFalso()), reloj)
    por_numero = {r.numero: r for r in resultados}

    fallidos = sorted(n for n, r in por_numero.items() if r.estado == FALLO)
    assert fallidos == [3, 4, 6, 9]
    assert codigo_salida(resultados, ctx) == 1

    # El informe dice por qué falla cada uno.
    assert "max(local, recibido) + 1" in por_numero[3].detalle
    assert "quedó en 7" in por_numero[3].detalle
    assert por_numero[4].codigo_http == 500
    assert "reintenta el duplicado" in por_numero[4].detalle
    assert por_numero[6].codigo_http == 200
    assert "4004 ms" in por_numero[6].detalle
    assert "caso 6" in por_numero[9].detalle
    # El reloj tampoco sube en el caso 7, pero eso es solo advertencia.
    assert por_numero[7].estado == ADVERTENCIA
    assert por_numero[5].estado == PASO
    assert por_numero[8].estado == PASO


def test_tiempo_de_espera_real_falla_el_caso_y_el_9():
    """Con un transporte que agota la espera (lo que hace httpx con un servidor lento)."""
    grupo = GrupoConforme()
    base = transporte(grupo)

    def manejar(peticion: httpx.Request) -> httpx.Response:
        if peticion.method == "POST" and "prioridad" in json.loads(peticion.content):
            raise httpx.ReadTimeout("lento", request=peticion)
        return base.handle_request(peticion)

    ctx, resultados = correr(manejar)
    por_numero = {r.numero: r for r in resultados}
    assert por_numero[6].estado == FALLO
    assert "tiempo de espera agotado" in por_numero[6].detalle
    assert por_numero[9].estado == FALLO
    assert codigo_salida(resultados, ctx) == 1


def test_sin_reloj_entero_los_casos_3_5_y_7_no_se_evaluan():
    def manejar(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path == "/fed/health":
            return httpx.Response(200, json={"server": "g9", "lamport": "42"})
        return httpx.Response(200, json={})

    ctx, resultados = correr(manejar)
    por_numero = {r.numero: r for r in resultados}
    assert por_numero[1].estado == FALLO
    assert "lamport no es un entero" in por_numero[1].detalle
    for n in (3, 5, 7):
        assert por_numero[n].estado == NO_EVALUADO
        assert "el caso 1 no dio un reloj entero" in por_numero[n].detalle
    # Los que no dependen del reloj sí se evalúan.
    assert por_numero[2].estado == PASO
    assert por_numero[4].estado == PASO
    assert codigo_salida(resultados, ctx) == 1


def test_lamport_42_punto_0_vale_como_entero():
    grupo = GrupoConforme()
    base = transporte(grupo)

    def manejar(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path == "/fed/health":
            return httpx.Response(200, json={"server": "g1", "lamport": float(grupo.lamport)})
        return base.handle_request(peticion)

    ctx, resultados = correr(manejar)
    assert estados(resultados)[1] == PASO
    assert ctx.lamport == 7


@pytest.mark.parametrize(
    "respuesta",
    [
        lambda: httpx.Response(200, text="<html><body>hola</body></html>", headers={"Content-Type": "text/html"}),
        lambda: httpx.Response(200, content=b"{no es json"),
        lambda: httpx.Response(200, json=[1, 2, 3]),
        lambda: httpx.Response(404, json={"detail": "Not Found"}),
        lambda: httpx.Response(200, content=b"\xff\xfe\x00basura"),
    ],
    ids=["html", "json-invalido", "lista", "404", "bytes-invalidos"],
)
def test_respuestas_inesperadas_no_tumban_el_script(respuesta):
    def manejar(peticion: httpx.Request) -> httpx.Response:
        return respuesta()

    ctx, resultados = correr(manejar)
    assert len(resultados) == 9
    assert estados(resultados)[1] == FALLO
    assert codigo_salida(resultados, ctx) == 1


def test_conexion_cortada_en_un_caso_queda_como_fallo_y_sigue():
    grupo = GrupoConforme()
    base = transporte(grupo)

    def manejar(peticion: httpx.Request) -> httpx.Response:
        if peticion.method == "POST" and json.loads(peticion.content).get("lamport") == 1:
            raise httpx.RemoteProtocolError("conexión cortada", request=peticion)
        return base.handle_request(peticion)

    ctx, resultados = correr(manejar)
    por_numero = {r.numero: r for r in resultados}
    assert por_numero[7].estado == FALLO
    assert "RemoteProtocolError" in por_numero[7].detalle
    assert len(resultados) == 9


def test_servidor_que_no_responde_para_en_el_caso_1():
    def manejar(peticion: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=peticion)

    ctx, resultados = correr(manejar)
    assert [r.numero for r in resultados] == [1]
    assert resultados[0].estado == FALLO
    assert "no respondió" in resultados[0].detalle
    assert ctx.sin_respuesta
    assert codigo_salida(resultados, ctx) == 2


def test_duplicado_que_mueve_el_reloj_es_advertencia():
    class GrupoQueCuentaDuplicados(GrupoConforme):
        def recibir(self, mensaje):
            if mensaje.get("id") in self.ids:
                self.lamport += 1
                return 200, {}, 0.0
            return super().recibir(mensaje)

    ctx, resultados = correr(transporte(GrupoQueCuentaDuplicados()))
    por_numero = {r.numero: r for r in resultados}
    assert por_numero[5].estado == ADVERTENCIA
    assert codigo_salida(resultados, ctx) == 0  # una advertencia no cambia el código


@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [(200, "aceptó un mensaje"), (500, "hizo fallar al servidor")],
)
def test_mensaje_sin_id_aceptado_o_con_5xx_es_advertencia(codigo, esperado):
    grupo = GrupoConforme()
    base = transporte(grupo)

    def manejar(peticion: httpx.Request) -> httpx.Response:
        if peticion.method == "POST" and "id" not in json.loads(peticion.content):
            return httpx.Response(codigo, json={})
        return base.handle_request(peticion)

    ctx, resultados = correr(manejar)
    caso_8 = {r.numero: r for r in resultados}[8]
    assert caso_8.estado == ADVERTENCIA
    assert esperado in caso_8.detalle
    assert codigo_salida(resultados, ctx) == 0


def test_solo_llama_a_la_url_dada_y_solo_envia_los_mensajes_de_los_casos():
    grupo = GrupoConforme()
    ctx, resultados = correr(transporte(grupo))

    hosts = {(p.url.scheme, p.url.host, p.url.port) for p in grupo.peticiones}
    assert hosts == {("http", "grupo.prueba", 8000)}

    posts = [json.loads(p.content) for p in grupo.peticiones if p.method == "POST"]
    # Casos 2, 4 (el duplicado), 6, 7 y 8.
    assert len(posts) == 5
    for mensaje in posts:
        assert mensaje["origin"] == ORIGEN_PRUEBA
        assert mensaje["from"] == "conformidad@conformidad"
        assert mensaje["body"] == CUERPO_PRUEBA
        assert isinstance(mensaje["seq"], int) and mensaje["seq"] >= 1
        assert mensaje["sent_at"].endswith("Z")
    assert posts[0] == posts[1]  # el duplicado es idéntico
    assert posts[0]["lamport"] == 7 + 100  # L + 100
    assert posts[3]["lamport"] == 1
    assert "id" not in posts[4]
    assert len({m["id"] for m in posts if "id" in m}) == 3


def test_url_con_ruta_base():
    grupo = GrupoConforme()
    ctx, resultados = correr(transporte(grupo), url="http://grupo.prueba:8000/chat")
    assert {p.url.path for p in grupo.peticiones} == {"/chat/fed/health", "/chat/fed/messages"}
