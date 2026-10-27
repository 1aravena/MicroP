import csv
import io
import sqlite3

import pytest

from backend.errors import BackendError, NotFound, StorageError
from backend.protocol import CSV_HEADER, default_config, parse_sample
from backend.storage import Store, utc_now


def add(store, capture, number=1):
    config = default_config("UNO")
    sample = parse_sample(f"UNO,{number},{number * 1000},NA,NA,NA,100,1", config)
    return store.add_sample(capture, sample, config["enabled"], utc_now())


def test_restart_preserves_samples_and_marks_unfinished_captures(tmp_path):
    path = tmp_path / "data.sqlite"
    store = Store(path)
    capture = store.create_capture("UNO", default_config("UNO"))
    add(store, capture)
    store.close()  # Simula salida sin finalizar la captura, sin manipular equipos reales.
    reopened = Store(path)
    try:
        metadata = reopened.capture(capture)
        assert metadata["status"] == "interrupted"
        assert metadata["sampleCount"] == 1
        assert metadata["endReason"] == "service_restart"
        assert reopened.page("samples")["items"][0]["distanceCm"] is None
        assert any(item["type"] == "INTERRUPTED" for item in reopened.page("incidents")["items"])
    finally:
        reopened.close()


def test_second_instance_cannot_recover_live_capture(tmp_path):
    path = tmp_path / "data.sqlite"
    store = Store(path)
    capture = store.create_capture("UNO", default_config("UNO"))
    try:
        with pytest.raises(StorageError, match="Otra instancia"):
            Store(path)
        assert store.capture(capture)["status"] == "capturing"
    finally:
        store.close()


def test_duplicates_partial_values_and_capture_mask(tmp_path):
    store = Store(tmp_path / "data.sqlite")
    try:
        capture = store.create_capture("UNO", default_config("UNO"))
        first = add(store, capture)
        with pytest.raises(BackendError, match="duplicado"):
            add(store, capture)
        assert store.capture(capture)["sampleCount"] == 1
        assert first["enabled"]["hc"] is True
        assert first["pir"] is None
        assert store.health()["ok"]
        store.end_capture(capture, "stopped", "manual_stop")
        with pytest.raises(BackendError):
            add(store, capture, 2)
    finally:
        store.close()


def test_pagination_and_bounded_snapshot_export(tmp_path):
    store = Store(tmp_path / "data.sqlite")
    try:
        capture = store.create_capture("UNO", default_config("UNO"))
        for number in range(1, 4):
            add(store, capture, number)
        first = store.page("samples", limit=2)
        assert len(first["items"]) == 2
        second = store.page("samples", after_id=first["nextCursor"], limit=2)
        assert [item["sequence"] for item in second["items"]] == [3]
        export = store.export("samples", capture_id=capture)
        add(store, capture, 4)  # La descarga no persigue datos agregados despues del corte.
        contents = "".join(export)
        rows = list(csv.reader(io.StringIO(contents.lstrip("\ufeff"))))
        assert ",".join(rows[0]) == CSV_HEADER
        assert len(rows) == 4
        assert rows[1][2:] == ["UNO", "1", "1000", "NA", "NA", "NA", "100", "1"]
        store.incident("UNO", "DEVICE", '@ERR,"dato"', capture)
        incidents = "".join(store.export("incidents", capture_id=capture))
        assert "'@ERR" in incidents
        with pytest.raises(NotFound):
            store.capture("missing")
        with pytest.raises(ValueError):
            store.page("samples", limit=501)
    finally:
        store.close()


def test_unknown_database_is_not_replaced(tmp_path):
    path = tmp_path / "foreign.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE keep_me(value TEXT)")
        db.execute("INSERT INTO keep_me VALUES('original')")
    with pytest.raises(StorageError, match="sin esquema conocido"):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM keep_me").fetchone()[0] == "original"


def test_unsupported_schema_is_not_recreated(tmp_path):
    path = tmp_path / "newer.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(StorageError, match="no compatible"):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99
