"""Contrato: ejemplos y respuestas reales contra los esquemas de la especificación.

Una diferencia entre el código y la especificación rompe esta prueba, no a un grupo
(CS-003 §A, punto 2).
"""

import json
import os
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from central.modelo import SPEC_VERSION

from .conftest import TOKEN, esperar, mensaje

ESPEC = Path(os.environ.get("RUTA_ESPECIFICACION") or Path(__file__).resolve().parents[2] / "especificacion")
ARCHIVOS = {"central": "openapi-central.yaml", "grupo": "openapi-grupo.yaml"}
SPECS = {clave: yaml.safe_load((ESPEC / nombre).read_text(encoding="utf-8")) for clave, nombre in ARCHIVOS.items()}
REGISTRO = Registry().with_resources(
    (f"urn:{clave}", Resource(contents=spec, specification=DRAFT202012)) for clave, spec in SPECS.items()
)


def _puntero(partes) -> str:
    return "#/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in partes)


def validador(clave: str, partes: list) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"urn:{clave}{_puntero(partes)}"}, registry=REGISTRO)


def esquema_de_respuesta(ruta: str, metodo: str, codigo: int, clave: str = "central") -> list:
    respuesta = SPECS[clave]["paths"][ruta][metodo]["responses"][str(codigo)]
    if "$ref" in respuesta:
        nombre = respuesta["$ref"].rsplit("/", 1)[-1]
        return ["components", "responses", nombre, "content", "application/json", "schema"]
    return ["paths", ruta, metodo, "responses", str(codigo), "content", "application/json", "schema"]


def cumple(ruta: str, metodo: str, respuesta) -> None:
    v = validador("central", esquema_de_respuesta(ruta, metodo, respuesta.status_code))
    errores = [f"{e.message} en {list(e.absolute_path)}" for e in v.iter_errors(respuesta.json())]
    assert not errores, f"{metodo.upper()} {ruta} {respuesta.status_code}: {errores}"


# --- La especificación misma ------------------------------------------------------------


def test_la_version_del_central_es_la_de_la_especificacion():
    assert SPECS["central"]["info"]["version"] == SPECS["grupo"]["info"]["version"] == SPEC_VERSION


def _ejemplos_json():
    for clave, spec in SPECS.items():
        for ruta, item in spec["paths"].items():
            for metodo, op in item.items():
                if not isinstance(op, dict):
                    continue
                medios = []
                if "requestBody" in op:
                    medios.append((["paths", ruta, metodo, "requestBody", "content"], op["requestBody"]["content"]))
                for codigo, resp in op.get("responses", {}).items():
                    if "content" in resp:
                        medios.append((["paths", ruta, metodo, "responses", codigo, "content"], resp["content"]))
                for base, contenido in medios:
                    for nombre, ejemplo in contenido.get("application/json", {}).get("examples", {}).items():
                        yield pytest.param(clave, base + ["application/json", "schema"], nombre, ejemplo["value"],
                                           id=f"{clave}:{nombre}")
        for nombre_resp, resp in spec.get("components", {}).get("responses", {}).items():
            base = ["components", "responses", nombre_resp, "content", "application/json"]
            for nombre, ejemplo in resp["content"]["application/json"].get("examples", {}).items():
                yield pytest.param(clave, base + ["schema"], nombre, ejemplo["value"], id=f"{clave}:{nombre}")


@pytest.mark.parametrize(("clave", "partes", "nombre", "valor"), list(_ejemplos_json()))
def test_cada_ejemplo_es_su_archivo_y_valida(clave, partes, nombre, valor):
    archivo = ESPEC / "ejemplos" / f"{nombre}.json"
    assert json.loads(archivo.read_text(encoding="utf-8")) == valor
    assert not list(validador(clave, partes).iter_errors(valor))


def test_no_sobran_archivos_de_ejemplo():
    usados = {p.values[2] for p in _ejemplos_json()}
    assert {p.stem for p in (ESPEC / "ejemplos").glob("*.json")} == usados


# --- Respuestas reales ------------------------------------------------------------------


def test_respuestas_de_las_rutas_de_los_grupos(cliente):
    cumple("/register", "post", cliente.post("/register", json={"server": "g1", "url": "http://g1.prueba"}))
    cumple("/register", "post", cliente.post("/register", json={"server": "g1", "url": "http://g1.prueba"}))
    cumple("/register", "post", cliente.post("/register", json={"server": "g2", "mode": "pull"}))
    cumple("/register", "post", cliente.post("/register", json={"server": "g1"}))
    m = mensaje(origin="g3")
    cumple("/messages", "post", cliente.post("/messages", json=m))
    cumple("/messages", "post", cliente.post("/messages", json=m))
    cumple("/messages", "post", cliente.post("/messages", json=mensaje(lamport="42")))
    cumple("/messages", "post", cliente.post("/messages", content=b"{", headers={"content-type": "application/json"}))
    cumple("/history", "get", cliente.get("/history?since=0"))
    cumple("/history", "get", cliente.get("/history?after_seq=0&server=g2"))
    cumple("/history", "get", cliente.get("/history?after_seq=99"))
    cumple("/history", "get", cliente.get("/history?since=1&after_seq=1"))
    cumple("/history", "get", cliente.get("/history?limit=0"))
    cumple("/health", "get", cliente.get("/health"))


def test_respuestas_de_estado_y_administracion(cliente, crear_cliente):
    cliente.post("/register", json={"server": "g1", "url": "http://g1.prueba"})
    cliente.post("/register", json={"server": "g2", "mode": "pull"})
    cliente.post("/messages", json=mensaje(origin="g2"))
    cumple("/servers", "get", cliente.get("/servers"))
    admin = {"Authorization": f"Bearer {TOKEN}"}
    cumple("/admin/servers/{server}", "delete", cliente.delete("/admin/servers/g1", headers=admin))
    cumple("/admin/servers/{server}", "delete", cliente.delete("/admin/servers/g7", headers=admin))
    cumple("/admin/servers/{server}", "delete", cliente.delete("/admin/servers/g2"))
    cumple("/admin/reset", "post", cliente.post("/admin/reset", headers=admin))
    cumple("/admin/reset", "post", cliente.post("/admin/reset", headers={"Authorization": "Bearer x"}))
    with crear_cliente(admin_token="") as sin_token:
        cumple("/admin/reset", "post", sin_token.post("/admin/reset", headers=admin))


def test_lo_que_viaja_en_push_cumple_el_contrato_del_grupo(cliente, grupos):
    cliente.post("/register", json={"server": "g1", "url": "http://g1.prueba"})
    sin_opcionales = {k: v for k, v in mensaje(origin="g2").items() if k not in ("sent_at", "body")}
    cliente.post("/messages", json=sin_opcionales)
    cliente.post("/messages", json=mensaje(origin="g2", extra="se ignora"))
    esperar(lambda: len(grupos.recibidos["g1.prueba"]) == 2)
    v = validador("grupo", ["paths", "/fed/messages", "post", "requestBody", "content", "application/json", "schema"])
    for enviado in grupos.recibidos["g1.prueba"]:
        assert not list(v.iter_errors(enviado))
        assert "extra" not in enviado
    assert grupos.recibidos["g1.prueba"][0]["sent_at"] == "" and grupos.recibidos["g1.prueba"][0]["body"] == ""
