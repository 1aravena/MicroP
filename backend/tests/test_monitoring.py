import json
from types import SimpleNamespace
import threading

from backend.dataset import timestamp
from backend.experiment_store import ExperimentStore
from backend.monitoring import Monitoring
from backend.storage import Store
from .test_dataset import BASE, make_trial
from .test_ml_runtime import model_data


def monitor_fixture(tmp_path, with_model=True):
    store = Store(tmp_path / 'monitor.sqlite3')
    repo = ExperimentStore(store)
    _, trial = make_trial(store, repo, seconds=25)
    model_path = tmp_path / 'model.json'
    if with_model:
        model_path.write_text(json.dumps(model_data()))
    states = [{'origin': origin, 'config': capture['config'], 'lastReceivedAt': timestamp(BASE+24500)}
              for origin, capture in trial['captureDetails'].items()]
    access = SimpleNamespace(active=True, run_id='run-1', started_at=timestamp(BASE), captures=trial['captures'],
                             lock=threading.RLock(), core_issue=lambda states=None: '')
    service = SimpleNamespace(store=store, settings=SimpleNamespace(model_file=str(model_path)),
                              experiments=SimpleNamespace(simulated=True), snapshots=lambda: states)
    return store, trial, access, Monitoring(service, access)


def test_live_windows_bounded_idempotent_and_separate_from_dataset(tmp_path):
    store, trial, access, monitor = monitor_fixture(tmp_path)
    try:
        monitor.tick(); monitor.tick(); monitor.tick()
        rows = monitor.predictions()['items']
        assert len(rows) == 2
        assert rows[1]['endedAt'] == rows[0]['startedAt']
        assert all(row['label'] == 'anomalo' and not row['reasons'] for row in rows)
        with store.access() as db:
            assert db.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 2
            assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == 50
        access.active = False
        assert monitor.status()['latest'] is None and monitor.status()['state'] == 'inactive'
    finally:
        store.close()


def test_bad_quality_or_missing_model_never_becomes_normal_prediction(tmp_path):
    store, trial, access, monitor = monitor_fixture(tmp_path, with_model=False)
    try:
        with store.access(True) as db:
            db.execute('UPDATE samples SET lux=NULL WHERE origin=?', ('UNO',))
        monitor.tick()
        result = monitor.predictions()['items'][0]
        assert result['label'] is None and result['score'] is None
        assert 'insufficient_lux' in result['reasons'] and 'model_unavailable' in result['reasons']
        assert access.active
    finally:
        store.close()


def test_late_inference_after_deactivation_is_discarded(tmp_path):
    store, _, access, monitor = monitor_fixture(tmp_path)
    try:
        original = monitor.runtime.model.predict
        def late(features):
            access.active = False
            return original(features)
        monitor.runtime.model.predict = late
        monitor.tick()
        assert monitor.predictions()['items'] == []
    finally:
        store.close()
