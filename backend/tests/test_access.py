from dataclasses import replace
import json
import sqlite3
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.credentials import PinVerifier, set_pin
from backend.protocol import default_config
from backend.storage import Store
from .fakes import wait_for
from .test_experiments import new_session, new_trial, prepare

PIN = '804291'  # Credencial desechable exclusiva de pruebas.


def access_settings(settings):
    set_pin(settings.pin_file, PIN)
    return replace(settings, stale_after=60)


def acquire(client, factory):
    prepare(client)
    for origin in ('UNO', 'NANO'):
        assert client.post(f'/api/v1/boards/{origin}/start').status_code == 200
    factory.devices['UNO_PORT'].emit('UNO,1,1000,NA,NA,NA,120,0\n')
    factory.devices['NANO_PORT'].emit('NANO,1,1000,NA,1,0,NA,NA\n')
    wait_for(lambda: all(row['latestSample'] for row in client.get('/api/v1/boards').json()['items']))


def attempt(client, pin=PIN, request_id=None):
    return client.post('/api/v1/access/attempts', json={'requestId': request_id or str(uuid.uuid4()), 'pin': pin})


def test_pin_private_hash_and_no_default(tmp_path):
    path = tmp_path / 'pin.json'
    assert not PinVerifier(path).verify(PIN)
    set_pin(path, PIN)
    assert PIN not in path.read_text()
    assert PinVerifier(path).verify(PIN)
    assert not PinVerifier(path).verify('000001')
    with pytest.raises(Exception):
        set_pin(path, 'invalid')


def test_access_cycle_led_idempotence_and_exclusion(settings, factory):
    with TestClient(create_app(access_settings(settings), factory)) as client:
        assert client.post('/api/v1/access/enable').status_code == 503
        acquire(client, factory)
        captures = [row['captureId'] for row in client.get('/api/v1/boards').json()['items']]
        assert client.post('/api/v1/access/enable').json()['active']
        assert client.get('/api/v1/ml/status').json()['modelState'] == 'no_model'
        request_id = str(uuid.uuid4())
        accepted = attempt(client, request_id=request_id)
        assert accepted.status_code == 200 and accepted.json()['authorization'] == 'allow'
        commands = len(factory.devices['NANO_PORT'].commands)
        assert attempt(client, request_id=request_id).json() == accepted.json()
        assert len(factory.devices['NANO_PORT'].commands) == commands
        rejected = attempt(client, '123456')
        assert rejected.status_code == 403 and rejected.json()['attempt']['authorization'] == 'deny'
        trial = new_trial(client, new_session(client))
        assert client.post(f'/api/v1/trials/{trial}/start').status_code == 409
        assert client.put('/api/v1/boards/NANO/sensors/pir', json={'enabled': False}).status_code == 409
        assert client.get('/api/v1/access/attempts/' + request_id).json()['signal'] == 'confirmed'
        exported = client.get('/api/v1/access/export.csv').text
        assert PIN not in exported and '123456' not in exported
        assert PIN not in json.dumps(factory.devices['NANO_PORT'].commands)
        client.post('/api/v1/access/disable')
        assert [row['captureId'] for row in client.get('/api/v1/boards').json()['items']] == captures
        assert all(row['phase'] == 'capturing' for row in client.get('/api/v1/boards').json()['items'])


def test_rate_limit_survives_restart_and_secrets_never_echo(settings, factory):
    settings = access_settings(settings)
    with TestClient(create_app(settings, factory)) as client:
        acquire(client, factory); client.post('/api/v1/access/enable')
        for _ in range(5):
            assert attempt(client, '123456').status_code == 403
        locked = attempt(client)
        assert locked.status_code == 429 and int(locked.headers['retry-after']) > 0
        bad = attempt(client, 'SECRET_INVALID_PIN')
        assert bad.status_code == 422 and 'SECRET_INVALID_PIN' not in bad.text
        malformed = client.post('/api/v1/access/attempts', content='{"pin":"SENSITIVE",', headers={'content-type': 'application/json'})
        assert 'SENSITIVE' not in malformed.text
        foreign = client.post('/api/v1/access/enable', headers={'Origin': 'https://elsewhere.example'})
        assert foreign.status_code == 403
    with TestClient(create_app(settings, factory)) as client:
        status = client.get('/api/v1/access/status').json()
        assert not status['active'] and status['retryAfter'] > 0


def test_old_firmware_remains_usable_and_refuses_access(settings, factory):
    factory.devices['NANO_PORT'].signal_supported = False
    with TestClient(create_app(access_settings(settings), factory)) as client:
        acquire(client, factory)
        assert client.post('/api/v1/access/enable').status_code == 503
        assert all(row['phase'] == 'capturing' for row in client.get('/api/v1/boards').json()['items'])


def test_signal_timeout_has_no_retry_and_requires_reactivation(settings, factory):
    with TestClient(create_app(access_settings(settings), factory)) as client:
        acquire(client, factory); client.post('/api/v1/access/enable')
        def lose_ack(command, port):
            if command.startswith('SIGNAL,') and command.endswith(',ALLOW'):
                return False
        factory.devices['NANO_PORT'].on_command = lose_ack
        request_id = str(uuid.uuid4())
        result = attempt(client, request_id=request_id)
        assert result.status_code == 504 and result.json()['attempt']['decision'] == 'unconfirmed'
        assert not client.get('/api/v1/access/status').json()['active']
        assert attempt(client, request_id=request_id).status_code == 504
        assert sum(command.endswith(',ALLOW') for command in factory.devices['NANO_PORT'].commands) == 1


def test_fault_suspends_access_but_preserves_independent_other_board(settings, factory):
    with TestClient(create_app(access_settings(settings), factory)) as client:
        acquire(client, factory); client.post('/api/v1/access/enable')
        factory.devices['NANO_PORT'].unplug()
        wait_for(lambda: not client.get('/api/v1/access/status').json()['active'])
        assert client.get('/api/v1/boards').json()['items'][0]['phase'] == 'capturing'
        assert attempt(client).status_code == 503


def test_pending_attempts_recovered_without_signal(tmp_path):
    path = tmp_path / 'recovery.sqlite3'
    store = Store(path)
    with store.access(True) as db:
        db.execute("INSERT INTO access_attempts(request_id,at,decision,authorization,signal,reason,snapshot_json) VALUES('r','t','pending','allow','pending','processing','{}')")
    store.close()
    reopened = Store(path)
    try:
        assert reopened.connection.execute('SELECT decision FROM access_attempts').fetchone()[0] == 'unconfirmed'
    finally:
        reopened.close()


def test_ml_error_does_not_change_permission_and_stale_data_suspends_it(settings, factory):
    settings = access_settings(settings)
    with open(settings.model_file, 'w') as file:
        file.write('{broken model')
    with TestClient(create_app(settings, factory)) as client:
        acquire(client, factory); client.post('/api/v1/access/enable')
        assert client.get('/api/v1/ml/status').json()['modelState'] == 'error'
        assert attempt(client).status_code == 200
        service = client.app.state.service
        service.board('UNO').since = time.monotonic() - 61
        wait_for(lambda: not client.get('/api/v1/access/status').json()['active'])
        with service.experiments.lock:
            pass  # Esperar la senal de falla que finaliza la suspension.
        assert attempt(client).status_code == 503
        assert service.board('NANO').snapshot()['phase'] == 'capturing'


def test_individual_stop_remains_available_during_access(settings, factory):
    with TestClient(create_app(access_settings(settings), factory)) as client:
        acquire(client, factory); client.post('/api/v1/access/enable')
        assert client.post('/api/v1/boards/UNO/stop').status_code == 200
        assert not client.get('/api/v1/access/status').json()['active']
        assert client.get('/api/v1/boards').json()['items'][1]['phase'] == 'capturing'
        assert client.post('/api/v1/boards/NANO/signal', json={'result':'ALLOW'}).status_code == 404


def test_attempts_exclude_concurrent_submissions(settings, factory, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    entered, release = threading.Event(), threading.Event()
    with TestClient(create_app(access_settings(settings), factory)) as client:
        acquire(client, factory); client.post('/api/v1/access/enable')
        def delayed(pin):
            entered.set(); release.wait(2); return True
        monkeypatch.setattr(client.app.state.service.access.pin, 'verify', delayed)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(attempt, client)
            assert entered.wait(1)
            try:
                second = pool.submit(attempt, client)
                assert second.result(timeout=1).status_code == 409
            finally:
                release.set()
            assert first.result(timeout=2).status_code == 200
        assert len(client.get('/api/v1/access/attempts').json()['items']) == 1
