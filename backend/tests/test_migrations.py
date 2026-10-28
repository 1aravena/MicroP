import sqlite3

import pytest

from backend import migrations
from backend.errors import StorageError
from backend.storage import SCHEMA, Store


def legacy(path):
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO captures(capture_id,origin,config_json,started_at,status) VALUES('original','UNO','{}','2026-10-27T12:00:00Z','stopped')")
        db.execute("INSERT INTO incidents(at,origin,type,description) VALUES('2026-10-27T12:00:00Z','UNO','TEST','registro original')")


def test_schema1_backup_and_upgrade_preserve_records(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    legacy(path)
    store = Store(path)
    backup = store.migration_backup
    try:
        assert store.health()['schemaVersion'] == 2
        assert store.capture('original')['origin'] == 'UNO'
        assert store.page('incidents')['items'][0]['description'] == 'registro original'
        assert store.connection.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 0
        with sqlite3.connect(backup) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 1
            assert db.execute('SELECT COUNT(*) FROM captures').fetchone()[0] == 1
    finally:
        store.close()
    reopened = Store(path)
    try:
        assert reopened.migration_backup is None
        assert reopened.capture('original')['id'] == 'original'
    finally:
        reopened.close()
    assert len(list(tmp_path.glob('*.bak'))) == 1


def test_failed_migration_rolls_back_without_recreating_database(tmp_path, monkeypatch):
    path = tmp_path / 'legacy.sqlite3'
    legacy(path)
    monkeypatch.setattr(migrations, 'SCHEMA_2', migrations.SCHEMA_2 + '\nINVALID SQL;')
    with pytest.raises(StorageError):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM captures').fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='trials'").fetchone()[0] == 0


def test_fresh_schema2_does_not_create_unnecessary_backup(tmp_path):
    store = Store(tmp_path / 'new.sqlite3')
    try:
        assert store.migration_backup is None
        assert store.health()['schemaVersion'] == 2
    finally:
        store.close()
