"""SQLite local: transacciones cortas, historia en disco y exportacion por bloques."""
from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import threading
import uuid

from .errors import BackendError, NotFound, StorageError
from .protocol import CSV_HEADER, INCIDENT_HEADER
from .migrations import SCHEMA_VERSION, upgrade


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


SCHEMA = """
CREATE TABLE captures (
 ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
 capture_id TEXT NOT NULL UNIQUE, origin TEXT NOT NULL CHECK(origin IN ('UNO','NANO')),
 config_json TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
 status TEXT NOT NULL, end_reason TEXT, sample_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE samples (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 capture_id TEXT NOT NULL REFERENCES captures(capture_id), origin TEXT NOT NULL,
 sequence INTEGER NOT NULL, received_at TEXT NOT NULL, time_ms INTEGER NOT NULL,
 distance_cm REAL, pir INTEGER, radar INTEGER, lux REAL, sound INTEGER,
 raw TEXT NOT NULL, enabled_json TEXT NOT NULL, UNIQUE(capture_id, sequence)
);
CREATE TABLE incidents (
 id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, origin TEXT NOT NULL,
 capture_id TEXT REFERENCES captures(capture_id), type TEXT NOT NULL, description TEXT NOT NULL
);
CREATE INDEX sample_origin_id ON samples(origin, id);
CREATE INDEX sample_capture_id ON samples(capture_id, id);
CREATE INDEX incident_capture_id ON incidents(capture_id, id);
CREATE INDEX incident_origin_id ON incidents(origin, id);
PRAGMA user_version = 1;
"""


class DatabaseLease:
    """Bloqueo de vida del proceso: otro servidor no debe recuperar capturas activas."""
    def __init__(self, path):
        self.file = open(str(path) + ".lock", "a+b")
        try:
            self.file.seek(0, 2)
            if self.file.tell() == 0:
                self.file.write(b"\0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            raise StorageError("Otra instancia utiliza esta base; no se recuperaron ni modificaron sus capturas.") from error

    def close(self):
        self.file.close()  # El SO libera el bloqueo; conservar el archivo evita carreras por inodo.


class Store:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        self.closed = False
        self.last_error = None
        self.connection = None
        self.lease = None
        try:
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
                self.lease = DatabaseLease(Path(self.path).resolve())
            self.connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False, isolation_level=None)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA busy_timeout=5000")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            new_database = version == 0
            if version == 0:
                existing = self.connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                if existing:
                    raise StorageError("Base existente sin esquema conocido; no se modifico ni borro.")
                self.connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")
            elif version not in (1, 2, SCHEMA_VERSION):
                raise StorageError(f"Esquema SQLite no compatible: {version}. No se borro la base.")
            self.migration_backup = upgrade(self.connection, self.path, backup=not new_database)
            self.connection.execute("PRAGMA journal_mode=DELETE")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.recover()
        except (sqlite3.Error, OSError) as error:
            if self.connection:
                self.connection.close()
            if self.lease:
                self.lease.close()
            raise StorageError(f"No se pudo abrir el almacenamiento: {error}") from error
        except Exception:
            if self.connection:
                self.connection.close()
            if self.lease:
                self.lease.close()
            raise

    @contextmanager
    def access(self, write=False):
        with self.lock:
            if self.closed:
                raise StorageError("El almacenamiento esta cerrado.")
            try:
                if write:
                    self.connection.execute("BEGIN IMMEDIATE")
                yield self.connection
                if write:
                    self.connection.commit()
            except sqlite3.IntegrityError as error:
                if write:
                    self._rollback()
                raise BackendError(f"Registro duplicado o inconsistente: {error}") from error
            except sqlite3.Error as error:
                if write:
                    self._rollback()
                self.last_error = str(error)
                raise StorageError(f"Fallo de almacenamiento: {error}") from error
            except Exception:
                if write:
                    self._rollback()
                raise

    def _rollback(self):
        try:
            self.connection.rollback()
        except sqlite3.Error:
            pass

    def _incident(self, db, origin, kind, description, capture_id=None):
        db.execute("INSERT INTO incidents(at,origin,capture_id,type,description) VALUES(?,?,?,?,?)",
                   (utc_now(), origin, capture_id, kind, str(description)[:2000]))

    def incident(self, origin, kind, description, capture_id=None):
        with self.access(True) as db:
            self._incident(db, origin, kind, description, capture_id)

    def create_capture(self, origin, config):
        capture_id = str(uuid.uuid4())
        at = utc_now()
        with self.access(True) as db:
            db.execute("INSERT INTO captures(capture_id,origin,config_json,started_at,status) VALUES(?,?,?,?,?)",
                       (capture_id, origin, json.dumps(config), at, "capturing"))
            self._incident(db, origin, "START", f"Captura {capture_id}", capture_id)
        return capture_id

    def end_capture(self, capture_id, status, reason):
        if capture_id is None:
            return
        with self.access(True) as db:
            capture = db.execute("SELECT origin,status FROM captures WHERE capture_id=?", (capture_id,)).fetchone()
            if capture is None:
                raise NotFound("Captura no encontrada.")
            if capture["status"] == "capturing":
                db.execute("UPDATE captures SET status=?,ended_at=?,end_reason=? WHERE capture_id=?",
                           (status, utc_now(), reason, capture_id))
                self._incident(db, capture["origin"], "END", reason, capture_id)

    def recover(self):
        with self.access(True) as db:
            unfinished = db.execute("SELECT capture_id,origin FROM captures WHERE status='capturing'").fetchall()
            for item in unfinished:
                db.execute("UPDATE captures SET status='interrupted',ended_at=?,end_reason='service_restart' WHERE capture_id=?",
                           (utc_now(), item["capture_id"]))
                self._incident(db, item["origin"], "INTERRUPTED", "Captura inconclusa al reiniciar el servicio.", item["capture_id"])
            db.execute("""UPDATE trials SET status='interrupted',ended_at=?,end_reason='service_restart',
                       reviewed=0,reviewed_at=?,analysis_state='pending'
                       WHERE status IN ('starting','running','stopping')""", (utc_now(), utc_now()))
            db.execute("UPDATE trials SET analysis_state='pending' WHERE analysis_state='processing'")
            db.execute("UPDATE access_attempts SET decision='unconfirmed',signal='unconfirmed',reason='service_restart' WHERE decision='pending'")

    def add_sample(self, capture_id, sample, enabled, received_at):
        with self.access(True) as db:
            capture = db.execute("SELECT origin,status FROM captures WHERE capture_id=?", (capture_id,)).fetchone()
            if capture is None or capture["status"] != "capturing" or capture["origin"] != sample["origin"]:
                raise BackendError("La captura no esta activa para este origen.")
            cursor = db.execute("""INSERT INTO samples(capture_id,origin,sequence,received_at,time_ms,
                distance_cm,pir,radar,lux,sound,raw,enabled_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (capture_id, sample["origin"], sample["sequence"], received_at, sample["timeMs"],
                 sample["distanceCm"], sample["pir"], sample["radar"], sample["lux"], sample["sound"],
                 sample["raw"], json.dumps(enabled)))
            db.execute("UPDATE captures SET sample_count=sample_count+1 WHERE capture_id=?", (capture_id,))
            return {**sample, "id": cursor.lastrowid, "captureId": capture_id, "receivedAt": received_at,
                    "enabled": dict(enabled)}

    def health(self):
        try:
            with self.access() as db:
                for table in ("captures", "samples", "incidents"):
                    db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
            return {"ok": self.last_error is None, "schemaVersion": SCHEMA_VERSION, "error": self.last_error}
        except StorageError as error:
            return {"ok": False, "schemaVersion": SCHEMA_VERSION, "error": str(error)}

    @staticmethod
    def _capture(row):
        return {"id": row["capture_id"], "cursor": row["ordinal"], "origin": row["origin"],
                "config": json.loads(row["config_json"]), "startedAt": row["started_at"], "endedAt": row["ended_at"],
                "status": row["status"], "endReason": row["end_reason"], "sampleCount": row["sample_count"]}

    @staticmethod
    def _sample(row):
        return {"id": row["id"], "captureId": row["capture_id"], "origin": row["origin"], "sequence": row["sequence"],
                "receivedAt": row["received_at"], "timeMs": row["time_ms"], "distanceCm": row["distance_cm"],
                "pir": row["pir"], "radar": row["radar"], "lux": row["lux"], "sound": row["sound"],
                "raw": row["raw"], "enabled": json.loads(row["enabled_json"])}

    @staticmethod
    def _event(row):
        return {"id": row["id"], "at": row["at"], "origin": row["origin"], "captureId": row["capture_id"],
                "type": row["type"], "description": row["description"]}

    def capture(self, capture_id):
        with self.access() as db:
            row = db.execute("SELECT * FROM captures WHERE capture_id=?", (capture_id,)).fetchone()
            if row is None:
                raise NotFound("Captura no encontrada.")
            return self._capture(row)

    def page(self, table, *, after_id=0, limit=100, origin=None, capture_id=None, cutoff=None, order="asc"):
        if table not in ("captures", "samples", "incidents"):
            raise ValueError("Tabla no permitida.")
        if type(limit) is not int or not 1 <= limit <= 500 or type(after_id) is not int or after_id < 0:
            raise ValueError("Paginacion invalida.")
        if order not in ("asc", "desc"):
            raise ValueError("Orden invalido.")
        column = "ordinal" if table == "captures" else "id"
        where, args = ["1=1"], []
        if order == "asc" or after_id:
            where.append(f"{column}{'>' if order == 'asc' else '<'}?")
            args.append(after_id)
        for name, value in (("origin", origin), ("capture_id", capture_id)):
            if value is not None:
                where.append(f"{name}=?")
                args.append(value)
        if cutoff is not None:
            where.append(f"{column}<=?")
            args.append(cutoff)
        with self.access() as db:
            rows = db.execute(f"SELECT * FROM {table} WHERE {' AND '.join(where)} ORDER BY {column} {order.upper()} LIMIT ?", (*args, limit)).fetchall()
        converter = {"captures": self._capture, "samples": self._sample, "incidents": self._event}[table]
        return {"items": [converter(row) for row in rows], "nextCursor": rows[-1][column] if rows else after_id}

    def export(self, table, *, origin=None, capture_id=None):
        if table not in ("samples", "incidents"):
            raise ValueError("Exportacion invalida.")
        with self.access() as db:
            cutoff = db.execute(f"SELECT COALESCE(MAX(id),0) FROM {table}").fetchone()[0]

        def chunks():
            yield "\ufeff" + (CSV_HEADER if table == "samples" else INCIDENT_HEADER) + "\r\n"
            cursor = 0
            while True:
                page = self.page(table, after_id=cursor, limit=500, origin=origin, capture_id=capture_id, cutoff=cutoff)
                if not page["items"]:
                    return
                buffer = io.StringIO(newline="")
                writer = csv.writer(buffer)
                for item in page["items"]:
                    if table == "samples":
                        writer.writerow([item["receivedAt"], item["captureId"], *item["raw"].split(",")])
                    else:
                        values = [item["at"], item["origin"], item["type"], item["description"]]
                        writer.writerow(["'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in values])
                yield buffer.getvalue()
                cursor = page["nextCursor"]
        return chunks()

    def close(self):
        with self.lock:
            if not self.closed:
                self.connection.close()
                if self.lease:
                    self.lease.close()
                self.closed = True

