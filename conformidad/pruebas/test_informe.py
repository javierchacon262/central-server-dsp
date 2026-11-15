"""Formato del informe, recorte del cuerpo y códigos de salida (CS-004, O1)."""

from __future__ import annotations

import io

import httpx
import pytest

from conformidad import VERSION_ESPECIFICACION, VERSION_SCRIPT
from conformidad.__main__ import normalizar_url, principal
from conformidad.casos import (
    ADVERTENCIA,
    ADVERTENCIA_SEVERIDAD,
    FALLO,
    OBLIGATORIO,
    PASO,
    Contexto,
    Resultado,
)
from conformidad.informe import MAX_CUERPO, codigo_salida, formatear, recortar
from pruebas.grupos_falsos import GrupoConErrores, GrupoConforme, RelojFalso, transporte


def contexto() -> Contexto:
    return Contexto(url="http://localhost:8000", cliente=None, server="g1")  # type: ignore[arg-type]


def correr_principal(argv, trans=None, reloj=None):
    salida, errores = io.StringIO(), io.StringIO()
    codigo = principal(argv, transporte=trans, reloj=reloj or RelojFalso(), salida=salida, errores=errores)
    return codigo, salida.getvalue(), errores.getvalue()


# --- Recorte del cuerpo ------------------------------------------------------------------


def test_recorta_el_cuerpo_a_300_caracteres():
    largo = "x" * 1000
    recortado = recortar(largo)
    assert recortado.startswith("x" * MAX_CUERPO + "...")
    assert "1000 caracteres en total" in recortado
    assert MAX_CUERPO == 300


def test_un_cuerpo_corto_no_se_recorta_y_queda_en_una_linea():
    assert recortar('{"a":\n  1}') == '{"a": 1}'
    assert recortar(None) == ""


# --- Formato ------------------------------------------------------------------------------


def test_informe_de_ejemplo_se_lee_bien():
    resultados = [
        Resultado(1, "GET /fed/health", OBLIGATORIO, PASO, "server=g1, lamport=7", 200, '{"server":"g1","lamport":7}', 12,
                  enviado="GET /fed/health", esperado="2xx con server y lamport"),
        Resultado(4, "Duplicado", OBLIGATORIO, FALLO, "respondió 500", 500, "y" * 500, 30,
                  enviado="POST /fed/messages", esperado="2xx"),
        Resultado(8, "Mensaje sin id", ADVERTENCIA_SEVERIDAD, ADVERTENCIA, "respondió 200", 200, "", 5),
    ]
    texto = formatear(resultados, contexto(), fecha="2026-11-15T18:00:00.000Z")

    assert "Caso 1 - GET /fed/health [obligatorio]" in texto
    assert "  Enviado:   GET /fed/health" in texto
    assert "  Esperado:  2xx con server y lamport" in texto
    assert "  Respuesta: 200 en 12 ms" in texto
    assert "  Resultado: PASA: server=g1, lamport=7" in texto
    assert "  Resultado: FALLA: respondió 500" in texto
    assert "  Resultado: ADVERTENCIA: respondió 200" in texto
    assert "  Cuerpo:    (vacío)" in texto
    assert "y" * 301 not in texto  # cuerpo recortado
    # Resumen final.
    assert "Servidor (server):        g1" in texto
    assert "Fecha (UTC):              2026-11-15T18:00:00.000Z" in texto
    assert f"Versión especificación:   {VERSION_ESPECIFICACION}" in texto
    assert f"Versión del script:       {VERSION_SCRIPT}" in texto
    assert "NO CONFORME: fallan los casos obligatorios 4" in texto
    assert "Advertencias:             1 (casos 8)" in texto
    # Texto plano: sin colores ni caracteres de control.
    assert "\x1b" not in texto
    assert all(c == "\n" or c.isprintable() for c in texto)


# --- Códigos de salida --------------------------------------------------------------------


def test_una_advertencia_no_cambia_el_codigo_de_salida():
    resultados = [
        Resultado(7, "Marca menor", OBLIGATORIO, ADVERTENCIA, "el reloj no subió 1"),
        Resultado(8, "Sin id", ADVERTENCIA_SEVERIDAD, ADVERTENCIA, "lo aceptó"),
    ]
    assert codigo_salida(resultados, contexto()) == 0


def test_un_obligatorio_fallido_sale_con_1():
    resultados = [Resultado(2, "Nuevo", OBLIGATORIO, FALLO, "500")]
    assert codigo_salida(resultados, contexto()) == 1


@pytest.mark.parametrize(
    "url",
    ["localhost:8000", "ftp://localhost:8000", "http://", "http://localhost:8000/?x=1", "http://localhost:abc"],
)
def test_url_invalida_sale_con_2(url):
    codigo, salida, errores = correr_principal([url])
    assert codigo == 2
    assert salida == ""
    assert "URL inválida" in errores


def test_normaliza_la_barra_final():
    assert normalizar_url(" http://localhost:8000/ ") == "http://localhost:8000"
    assert normalizar_url("https://a.trycloudflare.com/chat/") == "https://a.trycloudflare.com/chat"


def test_servidor_que_no_responde_sale_con_2_y_deja_informe():
    def manejar(peticion: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=peticion)

    codigo, salida, errores = correr_principal(["http://localhost:8000"], httpx.MockTransport(manejar))
    assert codigo == 2
    assert "SIN RESPUESTA" in salida
    assert "Caso 2" not in salida
    assert "no se ejecutan los demás casos" in errores


def test_grupo_conforme_sale_con_0_y_el_informe_va_a_la_salida_estandar():
    reloj = RelojFalso()
    codigo, salida, errores = correr_principal(
        ["http://localhost:8000"], transporte(GrupoConforme(), reloj), reloj
    )
    assert codigo == 0
    assert "CONFORME: pasan todos los casos obligatorios" in salida
    assert "Servidor (server):        gconforme" in salida
    # El progreso va a la salida de error, no al informe.
    assert "Caso 1/9" in errores
    assert "Caso 1/9" not in salida
    assert salida.count("Resultado: PASA") == 9


def test_grupo_con_errores_sale_con_1():
    reloj = RelojFalso()
    codigo, salida, _ = correr_principal(["http://localhost:8000"], transporte(GrupoConErrores(), reloj), reloj)
    assert codigo == 1
    assert "NO CONFORME: fallan los casos obligatorios 3, 4, 6, 9" in salida
