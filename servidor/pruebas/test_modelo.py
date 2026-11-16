"""Los 400 de CS-002 §2 y las reglas de registro de §3.1, a nivel de modelo."""

import pytest
from pydantic import ValidationError

from central.modelo import LAMPORT_MAXIMO, Mensaje, Registro

from .conftest import mensaje


def campos_con_error(modelo, datos) -> set[str]:
    with pytest.raises(ValidationError) as e:
        modelo.model_validate(datos)
    return {str(err["loc"][0]) for err in e.value.errors()}


def test_mensaje_valido_conserva_los_campos():
    m = Mensaje.model_validate(mensaje(lamport=7))
    assert (m.from_, m.origin, m.lamport) == ("ana@g3", "g3", 7)


@pytest.mark.parametrize("valor", ["42", 42.5, True, False, -1, LAMPORT_MAXIMO + 1, None, [42], float("nan")])
def test_lamport_invalido(valor):
    assert campos_con_error(Mensaje, mensaje(lamport=valor)) == {"lamport"}


def test_lamport_42_punto_0_se_acepta_como_42():
    m = Mensaje.model_validate(mensaje(lamport=42.0))
    assert m.lamport == 42 and isinstance(m.lamport, int)


def test_lamport_en_el_tope():
    assert Mensaje.model_validate(mensaje(lamport=LAMPORT_MAXIMO)).lamport == LAMPORT_MAXIMO


@pytest.mark.parametrize("campo", ["id", "from", "origin", "lamport"])
def test_obligatorio_ausente(campo):
    datos = mensaje()
    del datos[campo]
    assert campos_con_error(Mensaje, datos) == {campo}


@pytest.mark.parametrize("campo", ["id", "from", "origin"])
def test_obligatorio_vacio_o_de_otro_tipo(campo):
    assert campos_con_error(Mensaje, mensaje(**{campo: ""})) == {campo}
    assert campos_con_error(Mensaje, mensaje(**{campo: 5})) == {campo}


@pytest.mark.parametrize(("campo", "largo"), [("id", 101), ("from", 101), ("origin", 33),
                                              ("sent_at", 65), ("body", 10_001)])
def test_limites_de_largo(campo, largo):
    assert campos_con_error(Mensaje, mensaje(**{campo: "x" * largo})) == {campo}
    Mensaje.model_validate(mensaje(**{campo: "x" * (largo - 1)}))


@pytest.mark.parametrize("campo", ["sent_at", "body"])
def test_opcional_null_o_de_otro_tipo(campo):
    assert campos_con_error(Mensaje, mensaje(**{campo: None})) == {campo}
    assert campos_con_error(Mensaje, mensaje(**{campo: 3})) == {campo}


def test_opcionales_ausentes_quedan_como_texto_vacio():
    datos = mensaje()
    del datos["sent_at"], datos["body"]
    m = Mensaje.model_validate(datos)
    assert (m.sent_at, m.body) == ("", "")


def test_campos_desconocidos_se_ignoran():
    m = Mensaje.model_validate(mensaje(room="#general", extra={"x": 1}))
    assert "room" not in m.model_dump() and "extra" not in m.model_dump()


def test_varios_errores_a_la_vez():
    assert campos_con_error(Mensaje, {"lamport": "x", "body": None}) == {"id", "from", "origin", "lamport", "body"}


# --- Registro ------------------------------------------------------------------------


def test_registro_push_por_defecto_normaliza_la_url():
    r = Registro.model_validate({"server": "g1", "url": "HTTPS://abc.trycloudflare.com/"})
    assert (r.mode, r.url) == ("push", "https://abc.trycloudflare.com")


def test_registro_pull_sin_url():
    r = Registro.model_validate({"server": "g2", "mode": "pull"})
    assert (r.mode, r.url) == ("pull", None)


def test_registro_pull_no_valida_la_url():
    # A14: en pull la URL es informativa.
    assert Registro.model_validate({"server": "g2", "mode": "pull", "url": "lo que sea/"}).url == "lo que sea/"


@pytest.mark.parametrize("datos", [
    {"server": "g1"},
    {"server": "g1", "mode": "push"},
    {"server": "g1", "url": None},
    {"server": "g1", "url": "ftp://x.org"},
    {"server": "g1", "url": "x.org"},
    {"server": "g1", "url": "http://"},
    {"server": "g1", "url": "http://u:p@x.org"},
    {"server": "g1", "url": "http://x.org/?a=1"},
    {"server": "g1", "url": "http://x.org/" + "a" * 2048},
])
def test_registro_push_sin_url_valida(datos):
    assert campos_con_error(Registro, datos) == {"url"}


@pytest.mark.parametrize("nombre", ["", "g 1", "g1\n", "x" * 33, "gé", 1, None])
def test_registro_nombre_invalido(nombre):
    assert "server" in campos_con_error(Registro, {"server": nombre, "mode": "pull"})


def test_registro_nombre_distingue_mayusculas():
    assert Registro.model_validate({"server": "G1", "mode": "pull"}).server == "G1"


@pytest.mark.parametrize("modo", ["PUSH", "", None, 1])
def test_registro_modo_desconocido(modo):
    assert campos_con_error(Registro, {"server": "g1", "url": "http://x.org", "mode": modo}) == {"mode"}
