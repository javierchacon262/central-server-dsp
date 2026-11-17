"""Cada fila de las tablas de CS-002 §3.1–§3.6, contra la app real."""

import logging

import pytest

from central.errores import PROBLEMAS

from .conftest import TOKEN, esperar, mensaje, servidor

ADMIN = {"Authorization": f"Bearer {TOKEN}"}


# --- §3.1 POST /register ----------------------------------------------------------------


def test_registro_nuevo_en_push(cliente):
    r = cliente.post("/register", json={"server": "g1", "url": "http://g1.prueba/"})
    assert r.status_code == 200
    assert r.json() == {"server": "g1", "url": "http://g1.prueba", "mode": "push", "new": True}


def test_renovacion_conserva_y_actualiza(cliente):
    cliente.post("/register", json={"server": "g1", "url": "http://g1.prueba"})
    r = cliente.post("/register", json={"server": "g1", "url": "http://g1b.prueba"})
    assert r.status_code == 200 and r.json()["new"] is False and r.json()["url"] == "http://g1b.prueba"


def test_registro_en_pull_sin_url(cliente):
    r = cliente.post("/register", json={"server": "g2", "mode": "pull"})
    assert r.status_code == 200
    assert r.json() == {"server": "g2", "url": None, "mode": "pull", "new": True}


@pytest.mark.parametrize(("cuerpo", "campo"), [
    ({"url": "http://g1.prueba"}, "server"),
    ({"server": "g 1", "url": "http://g1.prueba"}, "server"),
    ({"server": "g1", "url": "http://g1.prueba", "mode": "both"}, "mode"),
    ({"server": "g1"}, "url"),
    ({"server": "g1", "url": "ftp://g1.prueba"}, "url"),
])
def test_registro_invalido(cliente, eventos, cuerpo, campo):
    r = cliente.post("/register", json=cuerpo)
    assert r.status_code == 400
    assert r.json()["error"] == "registro inválido"
    assert campo in [d["field"] for d in r.json()["detail"]]
    assert "REGISTRO_RECHAZADO" in eventos.text
    assert cliente.get("/servers").json()["servers"] == []


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000", "http://169.254.169.254", "http://localhost:8000",
                                 "http://192.168.0.20:8000"])
def test_registro_push_a_direccion_privada_en_la_nube(crear_cliente, url):
    with crear_cliente(permitir_url_privadas=False) as c:
        r = c.post("/register", json={"server": "g1", "url": url})
        assert r.status_code == 400 and r.json()["detail"][0]["field"] == "url"
        # En pull la URL no pasa por el filtro (A14).
        assert c.post("/register", json={"server": "g1", "url": url, "mode": "pull"}).status_code == 200


def test_tope_de_servidores(crear_cliente):
    with crear_cliente(max_servidores=2) as c:
        assert c.post("/register", json={"server": "g1", "mode": "pull"}).status_code == 200
        assert c.post("/register", json={"server": "g2", "mode": "pull"}).status_code == 200
        r = c.post("/register", json={"server": "g3", "mode": "pull"})
        assert r.status_code == 400 and r.json()["detail"][0]["field"] == "server"
        assert c.post("/register", json={"server": "g1", "mode": "pull"}).status_code == 200


def test_campos_desconocidos_en_el_registro_se_ignoran(cliente):
    r = cliente.post("/register", json={"server": "g2", "mode": "pull", "color": "azul"})
    assert r.status_code == 200 and "color" not in r.json()


# --- §3.2 POST /messages ----------------------------------------------------------------


def test_mensaje_nuevo_y_duplicado(cliente, eventos):
    m = mensaje()
    r1 = cliente.post("/messages", json=m)
    r2 = cliente.post("/messages", json=m)
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == {"id": m["id"], "seq": 1, "duplicate": False}
    assert r2.json() == {"id": m["id"], "seq": 1, "duplicate": True}
    assert "RECIBIDO" in eventos.text and "DUPLICADO_DESCARTADO" in eventos.text


def test_duplicado_distinto_queda_en_el_log(cliente, eventos):
    m = mensaje()
    cliente.post("/messages", json=m)
    cliente.post("/messages", json={**m, "body": "editado"})
    linea = next(r.getMessage() for r in eventos.records if "DUPLICADO_DESCARTADO" in r.getMessage())
    assert "distinto=true" in linea
    assert cliente.get("/history").json()[0]["body"] == m["body"]


def test_no_hace_falta_estar_registrado(cliente):
    assert cliente.post("/messages", json=mensaje(origin="g99")).status_code == 200


def test_lamport_como_texto_responde_400_con_detalle(cliente, eventos):
    r = cliente.post("/messages", json=mensaje(lamport="42"))
    assert r.status_code == 400
    assert r.json() == {"error": "mensaje inválido",
                        "detail": [{"field": "lamport", "problem": "debe ser un entero ≥ 0"}]}
    assert "RECHAZADO_400" in eventos.text and "origin=g3" in eventos.text


@pytest.mark.parametrize(("cambio", "campo"), [
    ({"body": None}, "body"), ({"body": "a" * 10_001}, "body"),
    ({"sent_at": None}, "sent_at"), ({"sent_at": "x" * 65}, "sent_at"),
])
def test_body_y_sent_at_invalidos_nombran_el_campo(cliente, cambio, campo):
    # El campo se llama `body`, como el prefijo que FastAPI pone en `loc`: no debe perderse.
    r = cliente.post("/messages", json=mensaje(**cambio))
    assert r.status_code == 400
    assert r.json()["detail"] == [{"field": campo, "problem": PROBLEMAS[campo]}]


@pytest.mark.parametrize("crudo", [b"{no es json", b"", b"\xff\xfe\x00"])
def test_json_mal_formado(cliente, crudo):
    r = cliente.post("/messages", content=crudo, headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json() == {"error": "JSON mal formado", "detail": []}


def test_cuerpo_que_no_es_objeto(cliente):
    r = cliente.post("/messages", json=[mensaje()])
    assert r.status_code == 400 and r.json()["detail"] == []


def test_acepta_json_sin_content_type(cliente):
    import json
    r = cliente.post("/messages", content=json.dumps(mensaje()).encode(), headers={"content-type": "text/plain"})
    assert r.status_code == 200


def test_campos_desconocidos_no_se_guardan(cliente):
    cliente.post("/messages", json=mensaje(room="#general"))
    assert set(cliente.get("/history").json()[0]) == {"id", "from", "origin", "lamport", "sent_at", "body", "seq"}


# --- §3.3 GET /history ------------------------------------------------------------------


def poblar(cliente):
    for id_, origin, lamport in [("c", "g2", 5), ("b", "g1", 5), ("z", "g9", 3), ("y", "g0", 8)]:
        cliente.post("/messages", json=mensaje(id=id_, origin=origin, lamport=lamport))


def test_since_inclusivo_ordenado_por_lamport_origin_id(cliente):
    poblar(cliente)
    assert [m["id"] for m in cliente.get("/history?since=5").json()] == ["b", "c", "y"]
    assert [m["id"] for m in cliente.get("/history").json()] == ["z", "b", "c", "y"]


def test_after_seq_en_orden_de_llegada(cliente):
    poblar(cliente)
    r = cliente.get("/history?after_seq=1").json()
    assert [(m["id"], m["seq"]) for m in r] == [("b", 2), ("z", 3), ("y", 4)]


def test_limit(cliente):
    poblar(cliente)
    assert len(cliente.get("/history?after_seq=0&limit=2").json()) == 2
    assert [m["id"] for m in cliente.get("/history?since=0&limit=1").json()] == ["z"]


def test_lista_vacia_no_es_404(cliente):
    r = cliente.get("/history?after_seq=50")
    assert r.status_code == 200 and r.json() == []


def test_since_y_after_seq_juntos(cliente):
    r = cliente.get("/history?since=1&after_seq=1")
    assert r.status_code == 400
    assert r.json() == {"error": "parámetros inválidos",
                        "detail": [{"field": "after_seq", "problem": "no se puede combinar con since"}]}


@pytest.mark.parametrize(("consulta", "campo"), [
    ("since=abc", "since"), ("since=-1", "since"), ("since=9007199254740992", "since"),
    ("after_seq=1.5", "after_seq"), ("limit=0", "limit"), ("limit=1001", "limit"),
])
def test_parametros_invalidos(cliente, consulta, campo):
    r = cliente.get(f"/history?{consulta}")
    assert r.status_code == 400
    assert r.json()["error"] == "parámetros inválidos" and r.json()["detail"][0]["field"] == campo


def test_server_en_pull_es_senal_de_vida(crear_cliente):
    with crear_cliente(ventana_pull_s=0.3) as c:
        c.post("/register", json={"server": "g2", "mode": "pull"})
        assert servidor(c, "g2")["state"] == "up"
        esperar(lambda: servidor(c, "g2")["state"] == "down")
        c.get("/history?after_seq=0&server=g2")
        assert servidor(c, "g2")["state"] == "up"
        # A16: un nombre no registrado se ignora y la consulta responde igual.
        assert c.get("/history?after_seq=0&server=nadie").status_code == 200


# --- §3.4 GET /health -------------------------------------------------------------------


def test_health(cliente):
    assert cliente.get("/health").json() == {"status": "ok", "spec_version": "1.0.0", "last_seq": 0}
    cliente.post("/messages", json=mensaje())
    assert cliente.get("/health").json()["last_seq"] == 1


# --- §3.5 Panel y /servers --------------------------------------------------------------


def test_servers_con_push_y_pull(cliente, grupos):
    grupos.lamport["g1.prueba"] = 45
    cliente.post("/register", json={"server": "g1", "url": "http://g1.prueba"})
    cliente.post("/register", json={"server": "g2", "mode": "pull"})
    cliente.post("/messages", json=mensaje(origin="g1"))
    esperar(lambda: servidor(cliente, "g1")["lamport"] == 45)
    esperar(lambda: servidor(cliente, "g1")["delivered_seq"] == 1)  # saltó el propio
    datos = cliente.get("/servers").json()
    assert datos["last_seq"] == 1
    g1, g2 = datos["servers"]
    assert g1["server"] == "g1" and g1["mode"] == "push" and g1["state"] == "up"
    assert g1["delivered_seq"] == 1 and g1["pending"] == 0 and g1["last_seen"]
    assert g2 == {**g2, "mode": "pull", "url": None, "state": "up", "lamport": None,
                  "delivered_seq": None, "pending": None}


def test_panel_html(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert 'id="servidores"' in r.text and 'id="general"' in r.text
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert "innerHTML" not in r.text


def test_ruta_desconocida_con_la_forma_de_error(cliente):
    r = cliente.get("/no-existe")
    assert r.status_code == 404 and r.json() == {"error": "ruta no encontrada", "detail": []}


# --- §3.6 Administración ----------------------------------------------------------------


def test_admin_sin_token_configurado_responde_403(crear_cliente):
    with crear_cliente(admin_token="") as c:
        assert c.post("/admin/reset", headers=ADMIN).status_code == 403
        assert c.delete("/admin/servers/g1").status_code == 403


@pytest.mark.parametrize("cabeceras", [{}, {"Authorization": "Bearer otro"}, {"Authorization": TOKEN},
                                       {"Authorization": f"Basic {TOKEN}"}])
def test_admin_con_token_ausente_o_incorrecto(cliente, cabeceras):
    r = cliente.post("/admin/reset", headers=cabeceras)
    assert r.status_code == 401 and r.json() == {"error": "token ausente o incorrecto", "detail": []}


def test_admin_quitar_servidor(cliente):
    cliente.post("/register", json={"server": "g3", "url": "http://g3.prueba"})
    assert cliente.delete("/admin/servers/g3", headers=ADMIN).json() == {"removed": "g3"}
    assert cliente.get("/servers").json()["servers"] == []
    r = cliente.delete("/admin/servers/g7", headers=ADMIN)
    assert r.status_code == 404 and r.json()["detail"][0]["field"] == "server"


def test_admin_reset_no_reutiliza_seq(cliente):
    for _ in range(3):
        cliente.post("/messages", json=mensaje())
    assert cliente.post("/admin/reset", headers=ADMIN).json() == {"deleted": 3, "last_seq": 3}
    assert cliente.get("/history").json() == []
    assert cliente.get("/health").json()["last_seq"] == 3
    assert cliente.post("/messages", json=mensaje()).json()["seq"] == 4
    assert [m["seq"] for m in cliente.get("/history?after_seq=3").json()] == [4]


def test_el_token_nunca_llega_al_log(cliente, eventos):
    cliente.post("/admin/reset", headers=ADMIN)
    cliente.post("/admin/reset", headers={"Authorization": "Bearer intento-fallido"})
    assert "ADMIN" in eventos.text
    assert TOKEN not in eventos.text and "intento-fallido" not in eventos.text


def test_formato_de_las_lineas_del_log(cliente, eventos):
    cliente.post("/messages", json=mensaje(id="x 1", body="hola"))
    linea = next(r.getMessage() for r in eventos.records if " RECIBIDO " in r.getMessage())
    fecha, quien, evento, *resto = linea.split(" ", 3)
    assert len(fecha) == 24 and fecha.endswith("Z") and quien == "central" and evento == "RECIBIDO"
    assert 'id="x 1"' in linea and "from=ana@g3" in linea and "seq=1" in linea
    assert all(r.levelno == logging.INFO for r in eventos.records)
