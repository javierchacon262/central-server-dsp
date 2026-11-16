"""Forma de la URL de push y destinos prohibidos en la nube (A2)."""

import asyncio

import pytest

from central.urls import es_destino_permitido, motivo_destino_prohibido, normalizar_url


@pytest.mark.parametrize(("entrada", "salida"), [
    ("http://g1.example.org", "http://g1.example.org"),
    ("https://abc.trycloudflare.com/", "https://abc.trycloudflare.com"),
    ("HTTPS://abc.trycloudflare.com///", "https://abc.trycloudflare.com"),
    ("http://1.2.3.4:8000/grupo1/", "http://1.2.3.4:8000/grupo1"),
    ("http://[2001:db8::1]:8000", "http://[2001:db8::1]:8000"),
])
def test_normalizar_url_valida(entrada, salida):
    assert normalizar_url(entrada) == salida


@pytest.mark.parametrize("entrada", [
    "", "g1.example.org", "ftp://x.org", "http://", "http:///ruta", " http://x.org",
    "http://x .org", "http://user:pw@x.org", "http://x.org?a=1", "http://x.org#f",
    "http://x.org:99999", "http://x.org:0", "http://x.org/" + "a" * 2048,
])
def test_normalizar_url_invalida(entrada):
    with pytest.raises(ValueError):
        normalizar_url(entrada)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000", "http://10.0.0.5", "http://172.16.3.4", "http://192.168.1.10",
    "http://169.254.169.254", "http://100.64.0.1", "http://0.0.0.0", "http://224.0.0.1",
    "http://[::1]", "http://[::ffff:127.0.0.1]", "http://[fe80::1]", "http://[fd00::1]",
    "http://localhost:8000", "http://nadie.invalid",
])
def test_destinos_prohibidos_en_la_nube(url):
    assert asyncio.run(motivo_destino_prohibido(url, permitir_privadas=False)) is not None
    assert asyncio.run(es_destino_permitido(url, permitir_privadas=False)) is False


@pytest.mark.parametrize("url", ["http://8.8.8.8", "https://1.1.1.1:443", "http://[2606:4700:4700::1111]"])
def test_destinos_publicos_permitidos(url):
    assert asyncio.run(es_destino_permitido(url, permitir_privadas=False)) is True


def test_en_el_portatil_de_respaldo_se_permiten_las_privadas():
    assert asyncio.run(es_destino_permitido("http://192.168.1.10:8000", permitir_privadas=True)) is True


def test_el_motivo_nombra_la_direccion():
    motivo = asyncio.run(motivo_destino_prohibido("http://localhost:8000", permitir_privadas=False))
    assert "localhost" in motivo and ("127.0.0.1" in motivo or "::1" in motivo)
