import hashlib
import json
from pathlib import Path
import zipfile

import pytest

pytest.importorskip('sklearn', reason='Entrenamiento se prueba en .venv-ml; Raspberry no necesita sklearn.')

from backend.dataset import export_dataset
from backend.experiment_store import ExperimentStore
from backend.storage import Store
from ml.evaluate import evaluate
from ml.package import DatasetPackage
from ml.train import train
from .test_dataset import make_trial


def package_fixture(tmp_path):
    store = Store(tmp_path / 'dataset.sqlite3')
    repository = ExperimentStore(store)
    sessions = []
    try:
        for partition, scenario in [('train','zona_vacia'), ('train','paso_breve'),
                                    ('train','acercamientos_repetidos'), ('train','permanencia_proxima'),
                                    ('test','zona_vacia'), ('test','permanencia_proxima')]:
            session, trial = make_trial(store, repository, partition=partition, scenario=scenario, seconds=30)
            # Variacion sintetica SOLO para probar el algoritmo, nunca una captura real.
            if scenario in ('acercamientos_repetidos', 'permanencia_proxima'):
                with store.access(True) as db:
                    for row in db.execute('SELECT observation_id,features_json FROM observations WHERE trial_id=?', (trial['id'],)).fetchall():
                        values = json.loads(row['features_json'])
                        values['distance_mean_cm'] = 5.; values['lux_mean'] = 300.
                        db.execute('UPDATE observations SET features_json=? WHERE observation_id=?', (json.dumps(values), row['observation_id']))
            repository.close_session(session['id']); sessions.append(session['id'])
        path = tmp_path / 'simulated.zip'
        with export_dataset(store, repository, sessions) as exported:
            path.write_bytes(exported.read())
        return path
    finally:
        store.close()


def test_training_evaluation_parity_and_simulation_never_counts_as_real(tmp_path):
    package = package_fixture(tmp_path)
    with pytest.raises(ValueError, match='simulado'):
        train(package, tmp_path / 'forbidden')
    report = train(package, tmp_path / 'trained', allow_simulated=True)
    assert not report['testUsedForFit'] and len(report['folds']) == 4
    model_path = tmp_path / 'trained/model.json'
    before = hashlib.sha256(model_path.read_bytes()).hexdigest()
    result = evaluate(package, model_path, tmp_path / 'evaluation', allow_simulated=True)
    assert result['modelId'] == report['modelId']
    assert result['testRows'] == 6 and result['realTestObservations'] == 0 and not result['minimumMet']
    assert not result['modelRefitted']
    assert hashlib.sha256(model_path.read_bytes()).hexdigest() == before
    assert (tmp_path / 'evaluation/confusion-matrix.csv').exists()
    assert result['metrics']['accuracy'] == 1  # Fixture sintetico separable, no resultado del prototipo.


def test_package_rejects_corrupted_content_without_extracting(tmp_path):
    original = package_fixture(tmp_path)
    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(bad, 'w') as destination:
        for name in source.namelist():
            destination.writestr(name, source.read(name) + (b'corruption' if name == 'train.csv' else b''))
    with pytest.raises(ValueError, match='Hash'):
        DatasetPackage(bad, allow_simulated=True)


def test_train_does_not_read_test_features_or_labels(tmp_path):
    original = package_fixture(tmp_path)
    changed = tmp_path / 'reserved.zip'
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(changed, 'w') as destination:
        manifest = json.loads(source.read('manifest.json'))
        reserved = b'This test content is deliberately unreadable until evaluation.'
        manifest['sha256']['test.csv'] = hashlib.sha256(reserved).hexdigest()
        manifest['sizesBytes']['test.csv'] = len(reserved)
        for name in source.namelist():
            destination.writestr(name, json.dumps(manifest).encode() if name == 'manifest.json' else reserved if name == 'test.csv' else source.read(name))
    assert train(changed, tmp_path / 'train_only', allow_simulated=True)['testReserved']
    with pytest.raises(ValueError, match='Columnas'):
        evaluate(changed, tmp_path / 'train_only/model.json', tmp_path / 'invalid_eval', allow_simulated=True)


def test_trained_json_runs_in_live_monitoring_without_changing_dataset_labels(tmp_path):
    from backend.ml_runtime import ModelRuntime
    from .test_monitoring import monitor_fixture
    from .test_dataset import BASE
    from backend.dataset import timestamp
    package = package_fixture(tmp_path)
    train(package, tmp_path / 'trained', allow_simulated=True)
    store, trial, access, monitor = monitor_fixture(tmp_path)
    try:
        monitor.runtime = ModelRuntime(tmp_path / 'trained/model.json', allow_simulated=True)
        with store.access(True) as db:
            for row in db.execute("SELECT id,sequence,time_ms FROM samples WHERE origin='UNO' AND received_at>=? AND received_at<?", (timestamp(BASE+10000), timestamp(BASE+20000))).fetchall():
                db.execute('UPDATE samples SET distance_cm=5,lux=300,raw=? WHERE id=?',
                           (f"UNO,{row['sequence']},{row['time_ms']},5,NA,NA,300,1", row['id']))
        monitor.tick(); monitor.tick()
        results = monitor.predictions()['items']
        assert [row['label'] for row in results] == ['anomalo', 'normal']
        with store.access() as db:
            assert db.execute('SELECT COUNT(*) FROM observations WHERE eligible=1').fetchone()[0] == 2
        assert access.active
    finally:
        store.close()
