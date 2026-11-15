"""Almacén: deduplicación concurrente, seq sin huecos ni reuso, orden y cursor."""

import threading

import pytest

from central.almacen import Almacen, TopeDeServidores
from central.modelo import Mensaje, Registro

from .conftest import mensaje

AHORA = "2026-11-15T14:00:00.000Z"


@pytest.fixture
def almacen(tmp_path) -> Almacen:
    a = Almacen(tmp_path / "central.db")
    a.inicializar()
    return a


def guardar(almacen: Almacen, **cambios) -> int:
    return almacen.guardar_mensaje(Mensaje.model_validate(mensaje(**cambios)), AHORA)[0]


def test_dieciseis_hilos_con_el_mismo_id_dejan_un_solo_mensaje(almacen):
    m = Mensaje.model_validate(mensaje(id="mismo"))
    resultados, barrera = [], threading.Barrier(16)

    def enviar():
        barrera.wait()
        resultados.append(almacen.guardar_mensaje(m, AHORA))

    hilos = [threading.Thread(target=enviar) for _ in range(16)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert len(almacen.historial_despues_de_seq(0, 1000)) == 1
    assert {seq for seq, _, _ in resultados} == {1}
    assert sum(nuevo for _, nuevo, _ in resultados) == 1


def test_duplicados_no_dejan_huecos_en_seq(almacen):
    assert guardar(almacen, id="a") == 1
    assert guardar(almacen, id="a") == 1
    assert guardar(almacen, id="a") == 1
    assert guardar(almacen, id="b") == 2
    assert almacen.ultimo_seq() == 2


def test_duplicado_distinto_gana_el_primero(almacen):
    guardar(almacen, id="a", body="primero")
    seq, nuevo, distinto = almacen.guardar_mensaje(Mensaje.model_validate(mensaje(id="a", body="otro")), AHORA)
    assert (seq, nuevo, distinto) == (1, False, True)
    assert almacen.historial_despues_de_seq(0, 10)[0].body == "primero"
    assert almacen.guardar_mensaje(Mensaje.model_validate(mensaje(id="a", body="primero")), AHORA)[2] is False


def test_seq_sigue_despues_de_borrar_el_historial(almacen):
    for i in range(3):
        guardar(almacen, id=f"m{i}")
    assert almacen.borrar_historial() == 3
    assert almacen.ultimo_seq() == 3
    assert almacen.historial_despues_de_seq(0, 10) == []
    assert guardar(almacen, id="nuevo") == 4


def test_orden_por_lamport_origin_id_y_since_inclusivo(almacen):
    guardar(almacen, id="c", origin="g2", lamport=5)
    guardar(almacen, id="b", origin="g1", lamport=5)
    guardar(almacen, id="a", origin="g1", lamport=5)
    guardar(almacen, id="z", origin="g9", lamport=3)
    guardar(almacen, id="y", origin="g0", lamport=8)
    assert [m.id for m in almacen.historial_desde_lamport(0, 100)] == ["z", "a", "b", "c", "y"]
    assert [m.id for m in almacen.historial_desde_lamport(5, 100)] == ["a", "b", "c", "y"]
    assert [m.id for m in almacen.historial_desde_lamport(5, 2)] == ["a", "b"]
    assert [m.id for m in almacen.historial_despues_de_seq(2, 100)] == ["a", "z", "y"]


def test_ultimo_seq_sin_mensajes_es_cero(almacen):
    assert almacen.ultimo_seq() == 0


def test_registro_push_arranca_en_el_ultimo_seq(almacen):
    guardar(almacen, id="antes")
    s, nuevo = almacen.registrar_servidor(Registro(server="g1", url="http://g1.prueba"), AHORA, 100)
    assert nuevo and s.entregado_seq == 1 and s.visto_en is None
    assert almacen.siguiente_para("g1") is None


def test_renovar_en_push_conserva_el_cursor(almacen):
    almacen.registrar_servidor(Registro(server="g1", url="http://g1.prueba"), AHORA, 100)
    guardar(almacen, id="m1", origin="g2")
    s, nuevo = almacen.registrar_servidor(Registro(server="g1", url="http://otro.prueba"), AHORA, 100)
    assert not nuevo and s.entregado_seq == 0 and s.url == "http://otro.prueba"
    assert almacen.siguiente_para("g1").id == "m1"


def test_pasar_de_pull_a_push_y_volver(almacen):
    s, _ = almacen.registrar_servidor(Registro(server="g1", mode="pull"), AHORA, 100)
    assert (s.entregado_seq, s.visto_en) == (None, AHORA)
    guardar(almacen, id="m1", origin="g2")
    s, _ = almacen.registrar_servidor(Registro(server="g1", url="http://g1.prueba"), AHORA, 100)
    assert (s.modo, s.entregado_seq, s.visto_en) == ("push", 1, None)
    s, _ = almacen.registrar_servidor(Registro(server="g1", mode="pull"), AHORA, 100)
    assert (s.modo, s.entregado_seq, s.lamport) == ("pull", None, None)


def test_tope_de_servidores(almacen):
    for i in range(3):
        almacen.registrar_servidor(Registro(server=f"g{i}", mode="pull"), AHORA, 3)
    with pytest.raises(TopeDeServidores):
        almacen.registrar_servidor(Registro(server="g9", mode="pull"), AHORA, 3)
    # Renovar uno existente sigue funcionando con el tope alcanzado.
    almacen.registrar_servidor(Registro(server="g0", mode="pull"), AHORA, 3)


def test_siguiente_para_salta_los_propios_y_el_cursor_solo_avanza(almacen):
    almacen.registrar_servidor(Registro(server="g1", url="http://g1.prueba"), AHORA, 100)
    guardar(almacen, id="p1", origin="g1")
    guardar(almacen, id="o1", origin="g2")
    guardar(almacen, id="p2", origin="g1")
    assert almacen.contar_pendientes("g1") == 1
    siguiente = almacen.siguiente_para("g1")
    assert siguiente.id == "o1"
    assert almacen.obtener_servidor("g1").entregado_seq == 1  # saltó p1
    almacen.avanzar_cursor("g1", siguiente.seq)
    assert almacen.siguiente_para("g1") is None
    assert almacen.obtener_servidor("g1").entregado_seq == 3  # saltó p2
    almacen.avanzar_cursor("g1", 1)
    assert almacen.obtener_servidor("g1").entregado_seq == 3
    assert almacen.contar_pendientes("g1") == 0


def test_listar_servidores_con_pendientes(almacen):
    almacen.registrar_servidor(Registro(server="g1", url="http://g1.prueba"), AHORA, 100)
    almacen.registrar_servidor(Registro(server="g2", mode="pull"), "2026-11-15T14:00:01.000Z", 100)
    guardar(almacen, id="a", origin="g2")
    guardar(almacen, id="b", origin="g1")
    s1, s2 = almacen.listar_servidores()
    assert (s1.nombre, s1.pendientes) == ("g1", 1)
    assert (s2.nombre, s2.pendientes) == ("g2", None)


def test_quitar_servidor(almacen):
    almacen.registrar_servidor(Registro(server="g1", mode="pull"), AHORA, 100)
    assert almacen.quitar_servidor("g1") is True
    assert almacen.quitar_servidor("g1") is False
    assert almacen.listar_servidores() == []


def test_latido_y_visto(almacen):
    almacen.registrar_servidor(Registro(server="g1", url="http://g1.prueba"), AHORA, 100)
    almacen.registrar_servidor(Registro(server="g2", mode="pull"), AHORA, 100)
    almacen.guardar_latido("g1", 45, "2026-11-15T14:00:05.000Z")
    almacen.guardar_latido("g1", None, "2026-11-15T14:00:10.000Z")
    almacen.marcar_visto("g2", "2026-11-15T14:00:07.000Z")
    almacen.marcar_visto("g1", "2026-11-15T14:00:09.000Z")  # en push no cuenta
    almacen.marcar_visto("nadie", AHORA)
    g1, g2 = almacen.obtener_servidor("g1"), almacen.obtener_servidor("g2")
    assert (g1.lamport, g1.visto_en) == (45, "2026-11-15T14:00:10.000Z")
    assert g2.visto_en == "2026-11-15T14:00:07.000Z"
