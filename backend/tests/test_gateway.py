"""Pasarela simulada exclusiva de pruebas; nunca declara datos reales."""
from dataclasses import replace
import time

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.config import Settings
from backend.errors import ValidationError
from backend.protocol import default_config
from .fakes import FakeFactory, FakePort, wait_for


class MasterPort(FakePort):
    def __init__(self):
        super().__init__('MASTER')
        self.requests = []
        self.blocked = set()
        self.hook = None

    def response(self, origin, identifier, payload):
        self.emit(f'@FROM,{origin},{identifier},{payload}\n')

    def write(self, data):
        text = data.decode('ascii').strip()
        self.commands.append(text)
        if text == 'GATEWAY_INFO':
            self.emit('@OK,GATEWAY,1,UNO,NANO,9600\n')
            return len(data)
        _, origin, identifier, command = text.split(',', 3)
        self.requests.append((origin, identifier, command))
        if self.hook and self.hook(origin, identifier, command) is False:
            return len(data)
        if origin in self.blocked:
            self.response(origin, identifier, '@ERR,GATEWAY,NANO_TIMEOUT')
        elif command == 'INFO':
            self.response(origin, identifier, f'@OK,INFO,2,{origin}')
        elif command == 'SIGNAL_CAPS':
            self.response(origin, identifier, '@OK,SIGNAL_CAPS,1')
        elif command.startswith('SIGNAL,') or command.startswith('ENABLE,'):
            self.response(origin, identifier, '@OK,' + command)
        else:
            self.response(origin, identifier, '@OK,' + command.split(',')[0])
        return len(data)


class MasterFactory(FakeFactory):
    is_simulated = True

    def __init__(self):
        super().__init__()
        self.devices = {'MASTER_PORT': MasterPort()}


def prepare(client):
    response = client.post('/api/v1/gateway/connect', json={'port': 'MASTER_PORT'})
    assert response.status_code == 200, response.text
    for origin in ('UNO', 'NANO'):
        response = client.put(f'/api/v1/boards/{origin}/config', json=default_config(origin))
        assert response.status_code == 200, response.text


@pytest.fixture
def gateway(settings):
    factory = MasterFactory()
    with TestClient(create_app(replace(settings, transport='gateway', serial_port='MASTER_PORT', stale_after=60), factory)) as client:
        yield client, factory, factory.devices['MASTER_PORT']


def test_master_uses_one_port_and_preserves_both_sources_and_exports(gateway):
    client, factory, master = gateway
    prepare(client)
    assert factory.opens == ['MASTER_PORT']
    assert client.get('/api/v1/scenarios').json()['acquisitionMode'] == 'simulated'
    health = client.get('/api/v1/health').json()
    assert health['transport']['mode'] == 'gateway' and health['transport']['nanoBaudrate'] == 9600
    assert health['runtime']['hostname']
    for origin in ('UNO', 'NANO'):
        assert client.post(f'/api/v1/boards/{origin}/start').status_code == 200
    master.response('UNO', 0, 'UNO,1,1000,50,NA,NA,120,0')
    master.response('NANO', 0, 'NANO,1,1000,NA,1,0,NA,NA')
    wait_for(lambda: all(row['sampleCount'] == 1 for row in client.get('/api/v1/boards').json()['items']))
    rows = client.get('/api/v1/samples').json()['items']
    assert {row['origin'] for row in rows} == {'UNO', 'NANO'}
    for row in client.get('/api/v1/boards').json()['items']:
        assert row['port'] == 'MASTER_PORT'
        exported = client.get(f"/api/v1/captures/{row['captureId']}/export.csv").text
        assert row['origin'] + ',1,1000,' in exported
    assert client.post('/api/v1/gateway/disconnect').status_code == 200
    assert not any(row['connected'] for row in client.get('/api/v1/boards').json()['items'])
    assert client.post('/api/v1/gateway/connect', json={'port': 'MASTER_PORT'}).status_code == 200
    assert len(factory.opens) == 2


def test_slave_failure_does_not_close_master_and_requires_explicit_reconnect(gateway):
    client, factory, master = gateway
    prepare(client)
    for origin in ('UNO', 'NANO'):
        assert client.post(f'/api/v1/boards/{origin}/start').status_code == 200
    master.blocked.add('NANO')
    wait_for(lambda: not client.get('/api/v1/boards').json()['items'][1]['connected'])
    states = client.get('/api/v1/boards').json()['items']
    assert states[0]['connected'] and states[0]['phase'] == 'capturing'
    master.response('UNO', 0, 'UNO,1,1000,50,NA,NA,100,0')
    wait_for(lambda: client.get('/api/v1/boards').json()['items'][0]['sampleCount'] == 1)
    master.blocked.clear()
    assert client.post('/api/v1/gateway/connect', json={'port': 'MASTER_PORT'}).status_code == 200
    assert factory.opens == ['MASTER_PORT']
    assert client.get('/api/v1/boards').json()['items'][1]['configured'] is False


def test_late_ack_wrong_origin_and_wrong_identifier_never_confirm_new_command(gateway):
    client, _, master = gateway
    prepare(client)
    def hook(origin, identifier, command):
        if origin == 'UNO' and command == 'START':
            master.response('NANO', identifier, '@OK,START')
            master.response('UNO', int(identifier) - 1, '@OK,START')
            return False
    master.hook = hook
    response = client.post('/api/v1/boards/UNO/start')
    assert response.status_code in (503, 504)
    assert not any(row['status'] == 'capturing' for row in client.get('/api/v1/captures').json()['items'])


def test_master_reset_invalidates_both_channels(gateway):
    client, _, master = gateway
    prepare(client)
    master.emit('@READY,2,UNO\n')
    wait_for(lambda: not any(row['connected'] for row in client.get('/api/v1/boards').json()['items']))
    assert client.get('/api/v1/health').json()['transport']['connected'] is False


def test_reserved_pins_wrong_port_and_trial_reservation(gateway):
    client, _, master = gateway
    assert client.post('/api/v1/gateway/connect', json={'port': 'OTHER_PORT'}).status_code == 503
    prepare(client)
    config = default_config('UNO'); config['hcTrigger'] = 2
    assert client.put('/api/v1/boards/UNO/config', json=config).status_code == 422
    session = client.post('/api/v1/sessions', json={'name': 'Fixture', 'responsible': 'Prueba', 'partition': 'train',
                        'source': 'simulated', 'conditions': 'UART simulado, sin hardware'}).json()
    trial = client.post(f"/api/v1/sessions/{session['id']}/trials", json={'scenario': 'zona_vacia'}).json()
    assert client.post(f"/api/v1/trials/{trial['id']}/start").status_code == 200
    assert client.post('/api/v1/gateway/disconnect').status_code == 409
    master.blocked.add('NANO')
    wait_for(lambda: client.get(f"/api/v1/trials/{trial['id']}").json()['status'] == 'interrupted')


def test_gateway_settings_validation():
    for values in ({'transport': 'invalid'}, {'serial_port': ''}, {'serial_port': None}):
        with pytest.raises(ValidationError):
            Settings.from_mapping(values)


def test_access_signal_and_pin_remain_independent_of_missing_model(settings):
    from backend.credentials import set_pin
    import uuid
    pin = '305817'  # Credencial desechable, solo en base temporal.
    set_pin(settings.pin_file, pin)
    factory = MasterFactory()
    with TestClient(create_app(replace(settings, transport='gateway', serial_port='MASTER_PORT', stale_after=60), factory)) as client:
        prepare(client)
        for origin in ('UNO', 'NANO'):
            assert client.post(f'/api/v1/boards/{origin}/start').status_code == 200
        master = factory.devices['MASTER_PORT']
        master.response('UNO', 0, 'UNO,1,1000,50,NA,NA,120,0')
        master.response('NANO', 0, 'NANO,1,1000,NA,1,0,NA,NA')
        wait_for(lambda: all(row['sampleCount'] == 1 for row in client.get('/api/v1/boards').json()['items']))
        assert client.post('/api/v1/access/enable').status_code == 200
        assert client.get('/api/v1/ml/status').json()['modelState'] == 'no_model'
        identifier = str(uuid.uuid4())
        allowed = client.post('/api/v1/access/attempts', json={'requestId': identifier, 'pin': pin})
        assert allowed.status_code == 200 and allowed.json()['signal'] == 'confirmed'
        count = len([row for row in master.requests if row[2].startswith('SIGNAL,')])
        assert client.post('/api/v1/access/attempts', json={'requestId': identifier, 'pin': pin}).json() == allowed.json()
        assert len([row for row in master.requests if row[2].startswith('SIGNAL,')]) == count
        denied = client.post('/api/v1/access/attempts', json={'requestId': str(uuid.uuid4()), 'pin': '000001'})
        assert denied.status_code == 403 and denied.json()['attempt']['authorization'] == 'deny'
        assert client.post('/api/v1/gateway/disconnect').status_code == 200
        assert client.get('/api/v1/access/status').json()['active'] is False


def test_coordinated_gateway_trial_produces_real_time_windows_in_simulated_database(gateway):
    client, _, master = gateway
    prepare(client)
    session = client.post('/api/v1/sessions', json={'name': 'Recorrido UART de prueba', 'responsible': 'Test automatizado',
                        'partition': 'train', 'source': 'simulated', 'conditions': 'Puerto simulado y muestras de fixture'}).json()
    trial = client.post(f"/api/v1/sessions/{session['id']}/trials", json={'scenario': 'zona_vacia'}).json()
    assert client.post(f"/api/v1/trials/{trial['id']}/start").status_code == 200
    captures = [row['captureId'] for row in client.get('/api/v1/boards').json()['items']]
    for index in range(1, 13):
        time.sleep(1)
        master.response('UNO', 0, f'UNO,{index},{index * 1000},100,NA,NA,120,0')
        master.response('NANO', 0, f'NANO,{index},{index * 1000},NA,0,0,NA,NA')
    wait_for(lambda: all(row['sampleCount'] == 12 for row in client.get('/api/v1/boards').json()['items']))
    # Reabrir/consultar no crea ni detiene capturas.
    assert [row['captureId'] for row in client.get('/api/v1/boards').json()['items']] == captures
    assert client.post(f"/api/v1/trials/{trial['id']}/stop").status_code == 200
    assert client.post(f"/api/v1/trials/{trial['id']}/review", json={'confirmed': True}).status_code == 202
    wait_for(lambda: client.get(f"/api/v1/trials/{trial['id']}").json()['analysisState'] == 'ready')
    summary = client.get('/api/v1/dataset/summary').json()
    assert client.post(f"/api/v1/sessions/{session['id']}/close").status_code == 200
    archive = client.get('/api/v1/dataset/export.zip', params={'session_id': session['id']})
    assert archive.status_code == 200
    import io, json, zipfile
    with zipfile.ZipFile(io.BytesIO(archive.content)) as package:
        manifest = json.loads(package.read('manifest.json'))
        assert manifest['source'] == 'simulated' and manifest['minimumMet'] is False
        assert len(package.read('train.csv').decode('utf-8-sig').splitlines()) >= 2
