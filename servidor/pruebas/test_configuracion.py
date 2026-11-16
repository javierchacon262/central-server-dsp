"""Configuración desde el entorno: valores por defecto, vacíos y errores juntos."""

import pytest

from central import __main__ as arranque
from central.configuracion import Configuracion, ErrorDeConfiguracion


def test_sin_variables_usa_los_valores_por_defecto():
    c = Configuracion.desde_entorno({})
    assert c == Configuracion()
    assert (c.puerto, c.max_servidores, c.heartbeat_intervalo_s, c.backoff_max_s) == (9000, 100, 5.0, 30.0)
    assert c.administracion_habilitada is False and c.permitir_url_privadas is False


def test_vacio_significa_por_defecto():
    assert Configuracion.desde_entorno({"PUERTO": "", "MAX_SERVIDORES": "  ", "ADMIN_TOKEN": ""}) == Configuracion()


def test_lee_cada_variable():
    c = Configuracion.desde_entorno({
        "ADMIN_TOKEN": "abc", "RUTA_BD": "/tmp/x.db", "PUERTO": "9100",
        "HEARTBEAT_INTERVALO_S": "2.5", "HEARTBEAT_FALLOS_PARA_CAIDO": "4",
        "BACKOFF_BASE_S": "0.5", "BACKOFF_MAX_S": "10", "HTTP_TIMEOUT_S": "1",
        "MAX_SERVIDORES": "20", "PERMITIR_URL_PRIVADAS": "true", "DOMINIO": "x.org",
    })
    assert c.admin_token == "abc" and c.ruta_bd == "/tmp/x.db" and c.puerto == 9100
    assert (c.heartbeat_intervalo_s, c.heartbeat_fallos_para_caido) == (2.5, 4)
    assert (c.backoff_base_s, c.backoff_max_s, c.http_timeout_s) == (0.5, 10.0, 1.0)
    assert c.max_servidores == 20 and c.permitir_url_privadas is True


def test_junta_todos_los_problemas():
    with pytest.raises(ErrorDeConfiguracion) as e:
        Configuracion.desde_entorno({"PUERTO": "nueve", "MAX_SERVIDORES": "0",
                                     "HTTP_TIMEOUT_S": "-1", "PERMITIR_URL_PRIVADAS": "quizas"})
    assert len(e.value.problemas) == 4


def test_backoff_base_mayor_que_el_maximo():
    with pytest.raises(ErrorDeConfiguracion):
        Configuracion.desde_entorno({"BACKOFF_BASE_S": "40"})


def test_el_resumen_no_incluye_el_token():
    resumen = Configuracion.desde_entorno({"ADMIN_TOKEN": "secreto-123"}).resumen()
    assert "secreto-123" not in str(resumen) and resumen["administracion"] == "habilitada"


def test_configuracion_invalida_sale_con_2_y_explica(monkeypatch, capsys):
    monkeypatch.setenv("PUERTO", "abc")
    monkeypatch.setenv("MAX_SERVIDORES", "-3")
    assert arranque.main() == 2
    salida = capsys.readouterr().err
    assert "PUERTO" in salida and "MAX_SERVIDORES" in salida
