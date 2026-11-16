"""Reenvío push y heartbeat (CS-002 §5), con grupos falsos sobre httpx.MockTransport."""

from .conftest import esperar, mensaje, servidor

G1 = "g1.prueba"


def registrar_g1(cliente):
    assert cliente.post("/register", json={"server": "g1", "url": f"http://{G1}"}).status_code == 200


def test_entrega_en_orden_con_seq_y_salta_los_propios(cliente, grupos):
    registrar_g1(cliente)
    enviados = [mensaje(origin="g2", lamport=i) for i in range(5)]
    for i, m in enumerate(enviados):
        cliente.post("/messages", json=m)
        if i == 2:
            cliente.post("/messages", json=mensaje(origin="g1", id="propio"))
    esperar(lambda: len(grupos.recibidos[G1]) == 5)
    recibidos = grupos.recibidos[G1]
    assert [m["id"] for m in recibidos] == [m["id"] for m in enviados]
    assert [m["seq"] for m in recibidos] == [1, 2, 3, 5, 6]
    assert set(recibidos[0]) == {"id", "from", "origin", "lamport", "sent_at", "body", "seq"}
    assert {k: recibidos[0][k] for k in enviados[0]} == enviados[0]
    esperar(lambda: servidor(cliente, "g1")["delivered_seq"] == 6)
    assert servidor(cliente, "g1")["pending"] == 0


def test_mensajes_anteriores_al_registro_no_se_reenvian(cliente, grupos):
    cliente.post("/messages", json=mensaje(origin="g2", id="viejo"))
    registrar_g1(cliente)
    cliente.post("/messages", json=mensaje(origin="g2", id="nuevo"))
    esperar(lambda: len(grupos.recibidos[G1]) == 1)
    assert grupos.recibidos[G1][0]["id"] == "nuevo"


def test_reintenta_un_503_con_el_mismo_id(cliente, grupos, eventos):
    grupos.codigos_mensajes[G1] = [503, "timeout", 500]
    registrar_g1(cliente)
    m = mensaje(origin="g2")
    cliente.post("/messages", json=m)
    esperar(lambda: len(grupos.recibidos[G1]) == 1)
    assert [i["id"] for i in grupos.intentos[G1]] == [m["id"]] * 4
    assert eventos.text.count("REINTENTO") == 3 and "causa=timeout" in eventos.text


def test_salta_un_4xx_y_sigue(cliente, grupos, eventos):
    grupos.codigos_mensajes[G1] = [400]
    registrar_g1(cliente)
    primero, segundo = mensaje(origin="g2"), mensaje(origin="g2")
    cliente.post("/messages", json=primero)
    cliente.post("/messages", json=segundo)
    esperar(lambda: len(grupos.recibidos[G1]) == 1)
    assert grupos.recibidos[G1][0]["id"] == segundo["id"]
    assert [i["id"] for i in grupos.intentos[G1]] == [primero["id"], segundo["id"]]
    assert "RECHAZADO_4XX" in eventos.text and "codigo=400" in eventos.text


def test_caida_pausa_y_vuelta_retoma(cliente, grupos, eventos):
    registrar_g1(cliente)
    esperar(lambda: grupos.consultas_salud[G1] >= 1)
    grupos.salud[G1] = 500
    esperar(lambda: servidor(cliente, "g1")["state"] == "down")
    assert "GRUPO_CAIDO" in eventos.text
    intentos = len(grupos.intentos[G1])
    cliente.post("/messages", json=mensaje(origin="g2", id="durante"))
    import time
    time.sleep(0.3)
    assert len(grupos.intentos[G1]) == intentos  # caído: no se intenta entregar
    assert servidor(cliente, "g1")["pending"] == 1
    grupos.salud[G1] = 200
    esperar(lambda: [m["id"] for m in grupos.recibidos[G1]] == ["durante"])
    assert servidor(cliente, "g1")["state"] == "up" and "GRUPO_VOLVIO" in eventos.text


def test_heartbeat_con_timeout_tambien_cuenta_como_fallo(cliente, grupos):
    grupos.salud[G1] = "timeout"
    registrar_g1(cliente)
    esperar(lambda: servidor(cliente, "g1")["state"] == "down")


def test_retoma_desde_el_cursor_al_reiniciar_el_central(crear_cliente, grupos):
    grupos.codigos_mensajes[G1] = [503] * 1000
    with crear_cliente() as c:
        registrar_g1(c)
        c.post("/messages", json=mensaje(origin="g2", id="pendiente"))
        esperar(lambda: len(grupos.intentos[G1]) >= 2)
        assert grupos.recibidos[G1] == []
    grupos.codigos_mensajes[G1].clear()
    with crear_cliente() as c:
        esperar(lambda: [m["id"] for m in grupos.recibidos[G1]] == ["pendiente"])
        esperar(lambda: servidor(c, "g1")["pending"] == 0)


def test_un_grupo_lento_no_frena_a_otro(cliente, grupos):
    grupos.retraso["lento.prueba"] = 0.4
    cliente.post("/register", json={"server": "lento", "url": "http://lento.prueba"})
    registrar_g1(cliente)
    for _ in range(3):
        cliente.post("/messages", json=mensaje(origin="g2"))
    esperar(lambda: len(grupos.recibidos[G1]) == 3, tiempo=0.6)
    assert len(grupos.recibidos["lento.prueba"]) < 3


def test_renovar_con_otra_url_redirige_los_reintentos(cliente, grupos):
    grupos.codigos_mensajes[G1] = [503] * 1000
    registrar_g1(cliente)
    m = mensaje(origin="g2")
    cliente.post("/messages", json=m)
    esperar(lambda: len(grupos.intentos[G1]) >= 1)
    cliente.post("/register", json={"server": "g1", "url": "http://g1-nuevo.prueba"})
    esperar(lambda: [x["id"] for x in grupos.recibidos["g1-nuevo.prueba"]] == [m["id"]])


def test_quitar_un_servidor_detiene_su_reenvio(cliente, grupos):
    from .test_rutas import ADMIN
    registrar_g1(cliente)
    cliente.delete("/admin/servers/g1", headers=ADMIN)
    cliente.post("/messages", json=mensaje(origin="g2"))
    import time
    time.sleep(0.2)
    assert grupos.intentos[G1] == []


def test_pasar_a_pull_detiene_el_reenvio(cliente, grupos):
    registrar_g1(cliente)
    cliente.post("/register", json={"server": "g1", "mode": "pull"})
    cliente.post("/messages", json=mensaje(origin="g2"))
    import time
    time.sleep(0.2)
    assert grupos.intentos[G1] == []
    assert servidor(cliente, "g1")["delivered_seq"] is None
