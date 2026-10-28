from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.protocol import default_config
from .fakes import wait_for


def new_session(client, partition='train'):
    response = client.post('/api/v1/sessions', json={'name': 'Sesion de prueba', 'responsible': 'QA',
                           'partition': partition, 'source': 'simulated', 'conditions': 'PERIFERICOS SIMULADOS'})
    assert response.status_code == 201, response.text
    return response.json()['id']


def prepare(client):
    for origin in ('UNO', 'NANO'):
        assert client.post(f'/api/v1/boards/{origin}/connect', json={'port': f'{origin}_PORT'}).status_code == 200
        assert client.put(f'/api/v1/boards/{origin}/config', json=default_config(origin)).status_code == 200


def new_trial(client, session):
    response = client.post(f'/api/v1/sessions/{session}/trials', json={'scenario': 'paso_breve'})
    assert response.status_code == 201
    return response.json()['id']


def test_coordinated_cycle_confirmation_and_readonly_partitions(settings, factory):
    with TestClient(create_app(replace(settings, stale_after=3.5), factory)) as client:
        assert len(client.get('/api/v1/scenarios').json()['items']) == 4
        assert client.get('/api/v1/scenarios').json()['acquisitionMode'] == 'simulated'
        session = new_session(client)
        trial = new_trial(client, session)
        assert client.post(f'/api/v1/trials/{trial}/start').status_code == 409
        prepare(client)
        running = client.post(f'/api/v1/trials/{trial}/start')
        assert running.status_code == 200 and running.json()['status'] == 'running'
        ids = running.json()['captures']
        assert len(ids) == 2 and ids['UNO'] != ids['NANO']
        assert client.get('/api/v1/trials/active').json()['trial']['id'] == trial
        assert client.get('/api/v1/boards').json()['items'][0]['trialId'] == trial
        for action in ('start', 'stop', 'disconnect'):
            assert client.post(f'/api/v1/boards/UNO/{action}').status_code == 409
        assert client.post(f'/api/v1/trials/{trial}/start').json()['captures'] == ids
        assert client.post(f'/api/v1/trials/{trial}/stop').json()['status'] == 'completed'
        assert client.post(f'/api/v1/sessions/{session}/close').status_code == 409
        assert client.post(f'/api/v1/trials/{trial}/review', json={'confirmed': True}).status_code == 202
        wait_for(lambda: client.get(f'/api/v1/trials/{trial}').json()['analysisState'] == 'ready')
        assert client.post(f'/api/v1/sessions/{session}/close').json()['status'] == 'closed'
        assert client.get('/api/v1/dataset/export.zip', params={'session_id': session}).status_code == 200
        assert client.post(f'/api/v1/sessions/{session}/trials', json={'scenario': 'zona_vacia'}).status_code == 409
        assert client.patch(f'/api/v1/sessions/{session}', json={'partition': 'test'}).status_code == 405
        assert client.get('/api/v1/trials/active').json()['trial'] is None


def test_partial_start_compensates_and_excludes_trial(settings, factory):
    def reject_start(command, port):
        if command == 'START':
            port.emit('@ERR,STATE,NOT_CONFIGURED\n')
            return False
    factory.devices['NANO_PORT'].on_command = reject_start
    with TestClient(create_app(replace(settings, stale_after=3.5), factory)) as client:
        prepare(client)
        trial = new_trial(client, new_session(client))
        assert client.post(f'/api/v1/trials/{trial}/start').status_code == 409
        result = client.get(f'/api/v1/trials/{trial}').json()
        assert result['status'] == 'interrupted' and result['reviewed'] is False
        assert not any(item['phase'] == 'capturing' for item in client.get('/api/v1/boards').json()['items'])
        assert result['captures']['UNO']
        assert client.post(f'/api/v1/trials/{trial}/review', json={'confirmed': True}).status_code == 409


def test_link_loss_stops_other_board_only_inside_coordinated_trial(settings, factory):
    with TestClient(create_app(replace(settings, stale_after=3.5), factory)) as client:
        prepare(client)
        trial = new_trial(client, new_session(client))
        assert client.post(f'/api/v1/trials/{trial}/start').status_code == 200
        factory.devices['NANO_PORT'].unplug()
        wait_for(lambda: client.get(f'/api/v1/trials/{trial}').json()['status'] == 'interrupted')
        states = client.get('/api/v1/boards').json()['items']
        assert states[0]['phase'] != 'capturing' and not states[1]['connected']
        assert client.get('/api/v1/dataset/summary').json()['real'] == {'train': 0, 'test': 0}


def test_two_concurrent_trials_cannot_reserve_same_boards(settings, factory):
    with TestClient(create_app(replace(settings, stale_after=3.5), factory)) as client:
        prepare(client)
        session = new_session(client)
        trials = [new_trial(client, session), new_trial(client, session)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(lambda trial: client.post(f'/api/v1/trials/{trial}/start').status_code, trials))
        assert sorted(codes) == [200, 409]


def test_restart_excludes_active_trial_and_never_resumes(settings, factory):
    settings = replace(settings, stale_after=3.5)
    with TestClient(create_app(settings, factory)) as client:
        prepare(client)
        trial = new_trial(client, new_session(client))
        assert client.post(f'/api/v1/trials/{trial}/start').status_code == 200
    opens = len(factory.opens)
    with TestClient(create_app(settings, factory)) as client:
        result = client.get(f'/api/v1/trials/{trial}').json()
        assert result['status'] == 'interrupted' and result['reviewed'] is False
        assert len(factory.opens) == opens
        assert client.get('/api/v1/trials/active').json()['trial'] is None


def test_simulated_transport_cannot_claim_real_source_and_validation(settings, factory):
    with TestClient(create_app(settings, factory)) as client:
        data = {'name': 'Sesion', 'responsible': 'QA', 'partition': 'test', 'source': 'real', 'conditions': 'Prueba'}
        assert client.post('/api/v1/sessions', json=data).status_code == 422
        data['source'] = 'simulated'; data['name'] = '   '
        assert client.post('/api/v1/sessions', json=data).status_code == 422
        session = new_session(client)
        assert client.post(f'/api/v1/sessions/{session}/trials', json={'scenario': 'inventado'}).status_code == 422
        trial = new_trial(client, session)
        assert client.post(f'/api/v1/trials/{trial}/review', json={'confirmed': 'yes'}).status_code == 422
        assert client.get('/api/v1/dataset/export.zip').status_code == 422
        assert client.post(f'/api/v1/trials/{trial}/stop').json()['status'] == 'interrupted'


def test_restart_recovers_pending_analysis_and_unfinished_database_state(settings, factory):
    from backend.experiment_store import ExperimentStore
    from backend.storage import Store
    from .test_dataset import make_trial
    store = Store(settings.database)
    repo = ExperimentStore(store)
    _, complete = make_trial(store, repo, seconds=20)
    repo.update_trial(complete['id'], analysis_state='processing')
    session, interrupted = make_trial(store, repo, seconds=10)
    repo.update_trial(interrupted['id'], status='running', reviewed=None)
    with store.access(True) as db:
        db.execute("UPDATE captures SET status='capturing',ended_at=NULL WHERE capture_id=?", (interrupted['captures']['UNO'],))
    store.close()
    with TestClient(create_app(settings, factory)) as client:
        wait_for(lambda: client.get(f"/api/v1/trials/{complete['id']}").json()['analysisState'] == 'ready')
        wait_for(lambda: client.get(f"/api/v1/trials/{interrupted['id']}").json()['analysisState'] == 'ready')
        result = client.get(f"/api/v1/trials/{interrupted['id']}").json()
        assert result['status'] == 'interrupted' and result['reviewed'] is False and result['eligibleCount'] == 0
        assert client.get(f"/api/v1/trials/{complete['id']}").json()['windowCount'] == 2
        assert client.get('/api/v1/trials/active').json()['trial'] is None
        assert factory.opens == []


def test_storage_failure_during_start_still_runs_compensation(settings, factory, monkeypatch):
    from backend.errors import StorageError
    with TestClient(create_app(replace(settings, stale_after=3.5), factory)) as client:
        prepare(client)
        trial = new_trial(client, new_session(client))
        manager = client.app.state.service.experiments
        def fail_link(*args):
            raise StorageError('Fallo simulado al asociar captura')
        monkeypatch.setattr(manager.repository, 'link', fail_link)
        assert client.post(f'/api/v1/trials/{trial}/start').status_code == 503
        assert all(row['phase'] != 'capturing' for row in client.get('/api/v1/boards').json()['items'])
        assert manager.active_id is None
        assert factory.devices['UNO_PORT'].commands[-1] == 'STOP'


def test_individual_control_rejected_immediately_during_trial_start(settings, factory):
    import threading
    entered, release = threading.Event(), threading.Event()
    def delayed(command, port):
        if command == 'START':
            entered.set()
            release.wait(2)
    factory.devices['UNO_PORT'].on_command = delayed
    with TestClient(create_app(replace(settings, command_timeout=2, stale_after=3.5), factory)) as client:
        prepare(client)
        trial = new_trial(client, new_session(client))
        with ThreadPoolExecutor(max_workers=2) as pool:
            starting = pool.submit(client.post, f'/api/v1/trials/{trial}/start')
            assert entered.wait(1)
            try:
                control = pool.submit(client.post, '/api/v1/boards/NANO/start')
                assert control.result(timeout=1).status_code == 409
            finally:
                release.set()
            assert starting.result(timeout=2).status_code == 200
