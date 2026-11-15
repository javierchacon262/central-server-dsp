"""Persistencia en SQLite (CS-002 §7).

Una conexión por operación, WAL y `BEGIN IMMEDIATE` en las escrituras, como en el
servidor de los grupos. Los métodos son síncronos: las rutas los llaman con
`asyncio.to_thread` para no frenar el bucle de eventos.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .modelo import Mensaje, MensajeGuardado, Registro, Servidor

ESQUEMA = """
CREATE TABLE IF NOT EXISTS mensajes (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,  -- nunca se reutiliza (A7)
    id          TEXT    NOT NULL UNIQUE,            -- clave de deduplicación
    remitente   TEXT    NOT NULL,                   -- campo `from` del protocolo
    origin      TEXT    NOT NULL,
    lamport     INTEGER NOT NULL,
    sent_at     TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    recibido_en TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS mensajes_orden ON mensajes (lamport, origin, id);

CREATE TABLE IF NOT EXISTS servidores (
    nombre        TEXT PRIMARY KEY,
    url           TEXT,
    modo          TEXT NOT NULL CHECK (modo IN ('push', 'pull')),
    registrado_en TEXT NOT NULL,
    renovado_en   TEXT NOT NULL,
    visto_en      TEXT,              -- última señal de vida
    entregado_seq INTEGER,           -- cursor push (D15); NULL en pull
    lamport       INTEGER            -- último reloj de /fed/health; NULL en pull
);
"""

_COLUMNAS_MENSAJE = "seq, id, remitente, origin, lamport, sent_at, body"


class TopeDeServidores(Exception):
    """Ya hay `MAX_SERVIDORES` registros y el nombre es nuevo (A1)."""


def _mensaje(fila: tuple) -> MensajeGuardado:
    seq, id_, remitente, origin, lamport, sent_at, body = fila
    return MensajeGuardado.model_construct(
        seq=seq, id=id_, from_=remitente, origin=origin, lamport=lamport, sent_at=sent_at, body=body
    )


def _servidor(fila: sqlite3.Row) -> Servidor:
    claves = fila.keys()
    return Servidor(
        nombre=fila["nombre"],
        url=fila["url"],
        modo=fila["modo"],
        registrado_en=fila["registrado_en"],
        renovado_en=fila["renovado_en"],
        visto_en=fila["visto_en"],
        entregado_seq=fila["entregado_seq"],
        lamport=fila["lamport"],
        pendientes=fila["pendientes"] if "pendientes" in claves else None,
    )


def _ultimo_seq(con: sqlite3.Connection) -> int:
    # sqlite_sequence y no MAX(seq): después de /admin/reset no hay mensajes, pero el
    # contador sigue donde iba (A7).
    fila = con.execute("SELECT seq FROM sqlite_sequence WHERE name = 'mensajes'").fetchone()
    return int(fila[0]) if fila else 0


class Almacen:
    def __init__(self, ruta: str | Path) -> None:
        self.ruta = str(ruta)

    @contextmanager
    def _conexion(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.ruta, timeout=10, isolation_level=None)
        try:
            con.execute("PRAGMA busy_timeout = 10000")
            con.row_factory = sqlite3.Row
            yield con
        finally:
            con.close()

    @contextmanager
    def _transaccion(self) -> Iterator[sqlite3.Connection]:
        with self._conexion() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")

    def inicializar(self) -> None:
        Path(self.ruta).parent.mkdir(parents=True, exist_ok=True)
        with self._conexion() as con:
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript(ESQUEMA)

    # --- Mensajes -------------------------------------------------------------------

    def guardar_mensaje(self, m: Mensaje, ahora: str) -> tuple[int, bool, bool]:
        """Devuelve (seq, nuevo, distinto). Un `id` conocido no tiene efecto (A4).

        `INSERT … WHERE NOT EXISTS` y no `ON CONFLICT DO NOTHING`: con AUTOINCREMENT,
        un insert ignorado consume un seq y dejaría huecos (CS-002 §7).
        """
        with self._transaccion() as con:
            cursor = con.execute(
                "INSERT INTO mensajes (id, remitente, origin, lamport, sent_at, body, recibido_en) "
                "SELECT ?, ?, ?, ?, ?, ?, ? "
                "WHERE NOT EXISTS (SELECT 1 FROM mensajes WHERE id = ?)",
                (m.id, m.from_, m.origin, m.lamport, m.sent_at, m.body, ahora, m.id),
            )
            if cursor.rowcount == 1:
                return int(cursor.lastrowid), True, False
            fila = con.execute(
                "SELECT seq, remitente, origin, lamport, sent_at, body FROM mensajes WHERE id = ?",
                (m.id,),
            ).fetchone()
            return int(fila["seq"]), False, tuple(fila)[1:] != m.contenido()

    def historial_desde_lamport(self, since: int, limite: int) -> list[MensajeGuardado]:
        with self._conexion() as con:
            filas = con.execute(
                f"SELECT {_COLUMNAS_MENSAJE} FROM mensajes WHERE lamport >= ? "
                "ORDER BY lamport, origin, id LIMIT ?",
                (since, limite),
            ).fetchall()
        return [_mensaje(tuple(f)) for f in filas]

    def historial_despues_de_seq(self, after_seq: int, limite: int) -> list[MensajeGuardado]:
        with self._conexion() as con:
            filas = con.execute(
                f"SELECT {_COLUMNAS_MENSAJE} FROM mensajes WHERE seq > ? ORDER BY seq LIMIT ?",
                (after_seq, limite),
            ).fetchall()
        return [_mensaje(tuple(f)) for f in filas]

    def ultimo_seq(self) -> int:
        with self._conexion() as con:
            return _ultimo_seq(con)

    def contar(self) -> tuple[int, int]:
        """(mensajes, servidores), para el log de arranque."""
        with self._conexion() as con:
            mensajes = con.execute("SELECT COUNT(*) FROM mensajes").fetchone()[0]
            servidores = con.execute("SELECT COUNT(*) FROM servidores").fetchone()[0]
        return int(mensajes), int(servidores)

    def borrar_historial(self) -> int:
        with self._transaccion() as con:
            return con.execute("DELETE FROM mensajes").rowcount

    # --- Servidores -----------------------------------------------------------------

    def registrar_servidor(self, r: Registro, ahora: str, maximo: int) -> tuple[Servidor, bool]:
        """Crea o renueva el registro. Devuelve (servidor, nuevo).

        Un servidor que entra en push, nuevo o desde pull, arranca su cursor en el último
        seq: lo anterior lo recupera con /history (A6). Renovar en push conserva el
        cursor (D16).
        """
        with self._transaccion() as con:
            actual = con.execute("SELECT * FROM servidores WHERE nombre = ?", (r.server,)).fetchone()
            visto = ahora if r.mode == "pull" else None
            if actual is None:
                total = con.execute("SELECT COUNT(*) FROM servidores").fetchone()[0]
                if total >= maximo:
                    raise TopeDeServidores()
                cursor = _ultimo_seq(con) if r.mode == "push" else None
                con.execute(
                    "INSERT INTO servidores (nombre, url, modo, registrado_en, renovado_en, "
                    "visto_en, entregado_seq, lamport) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                    (r.server, r.url, r.mode, ahora, ahora, visto, cursor),
                )
                nuevo = True
            else:
                if r.mode == "pull":
                    cursor, lamport = None, None
                elif actual["modo"] == "pull":
                    cursor, lamport = _ultimo_seq(con), None
                else:
                    cursor, lamport = actual["entregado_seq"], actual["lamport"]
                con.execute(
                    "UPDATE servidores SET url = ?, modo = ?, renovado_en = ?, "
                    "visto_en = COALESCE(?, CASE WHEN modo = ? THEN visto_en END), "
                    "entregado_seq = ?, lamport = ? WHERE nombre = ?",
                    (r.url, r.mode, ahora, visto, r.mode, cursor, lamport, r.server),
                )
                nuevo = False
            fila = con.execute("SELECT * FROM servidores WHERE nombre = ?", (r.server,)).fetchone()
        return _servidor(fila), nuevo

    def obtener_servidor(self, nombre: str) -> Servidor | None:
        with self._conexion() as con:
            fila = con.execute("SELECT * FROM servidores WHERE nombre = ?", (nombre,)).fetchone()
        return _servidor(fila) if fila else None

    def marcar_visto(self, nombre: str, ahora: str) -> None:
        """Señal de vida de un servidor en pull: una consulta con `server` (A3)."""
        with self._transaccion() as con:
            con.execute(
                "UPDATE servidores SET visto_en = ? WHERE nombre = ? AND modo = 'pull'",
                (ahora, nombre),
            )

    def guardar_latido(self, nombre: str, lamport: int | None, ahora: str) -> None:
        """Heartbeat exitoso de un servidor en push."""
        with self._transaccion() as con:
            con.execute(
                "UPDATE servidores SET visto_en = ?, lamport = COALESCE(?, lamport) "
                "WHERE nombre = ? AND modo = 'push'",
                (ahora, lamport, nombre),
            )

    def listar_servidores(self) -> list[Servidor]:
        with self._conexion() as con:
            filas = con.execute(
                "SELECT s.*, CASE WHEN s.modo = 'push' THEN ("
                "  SELECT COUNT(*) FROM mensajes m"
                "  WHERE m.seq > s.entregado_seq AND m.origin <> s.nombre"
                ") END AS pendientes "
                "FROM servidores s ORDER BY s.registrado_en, s.nombre"
            ).fetchall()
        return [_servidor(f) for f in filas]

    def quitar_servidor(self, nombre: str) -> bool:
        with self._transaccion() as con:
            return con.execute("DELETE FROM servidores WHERE nombre = ?", (nombre,)).rowcount == 1

    # --- Cursor de entrega push (D15) -----------------------------------------------

    def siguiente_para(self, nombre: str) -> MensajeGuardado | None:
        """El siguiente mensaje que no es del servidor, o None si no hay pendientes.

        Los mensajes propios que queden antes del siguiente (o al final) se saltan
        avanzando el cursor en la misma transacción (CS-002 §5, paso 1).
        """
        with self._transaccion() as con:
            fila = con.execute(
                "SELECT entregado_seq FROM servidores WHERE nombre = ? AND modo = 'push'", (nombre,)
            ).fetchone()
            if fila is None or fila[0] is None:
                return None
            cursor = int(fila[0])
            siguiente = con.execute(
                f"SELECT {_COLUMNAS_MENSAJE} FROM mensajes WHERE seq > ? AND origin <> ? "
                "ORDER BY seq LIMIT 1",
                (cursor, nombre),
            ).fetchone()
            if siguiente is None:
                tope = con.execute("SELECT MAX(seq) FROM mensajes WHERE seq > ?", (cursor,)).fetchone()[0]
            else:
                tope = con.execute(
                    "SELECT MAX(seq) FROM mensajes WHERE seq > ? AND seq < ?", (cursor, siguiente["seq"])
                ).fetchone()[0]
            if tope is not None:
                con.execute("UPDATE servidores SET entregado_seq = ? WHERE nombre = ?", (tope, nombre))
        return _mensaje(tuple(siguiente)) if siguiente else None

    def avanzar_cursor(self, nombre: str, seq: int) -> None:
        """Solo hacia adelante, y solo si el servidor sigue en push."""
        with self._transaccion() as con:
            con.execute(
                "UPDATE servidores SET entregado_seq = ? "
                "WHERE nombre = ? AND modo = 'push' AND entregado_seq < ?",
                (seq, nombre, seq),
            )

    def contar_pendientes(self, nombre: str) -> int:
        with self._conexion() as con:
            fila = con.execute(
                "SELECT COUNT(*) FROM mensajes m JOIN servidores s ON s.nombre = ? "
                "WHERE s.modo = 'push' AND m.seq > s.entregado_seq AND m.origin <> s.nombre",
                (nombre,),
            ).fetchone()
        return int(fila[0])
