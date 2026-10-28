import csv
import hashlib
import io
import json
import math
import zipfile

import pytest

from backend.dataset import FEATURES, analyze_trial, export_dataset, extract_window, milliseconds, timestamp
from backend.errors import BackendError, ValidationError
from backend.experiment_store import ExperimentStore
from backend.experiments import SCENARIO_BY_ID
from backend.protocol import default_config, parse_sample
from backend.storage import Store

BASE = milliseconds('2026-10-27T12:00:00.000Z')
CONFIGS = {origin: default_config(origin) for origin in ('UNO', 'NANO')}


def readings(seconds=10, missing_distance=False):
    rows = []
    pattern = [0, 1, 1, 0, 0, 1, 0, 1, 1, 0]
    for i in range(seconds):
        for j, origin in enumerate(('UNO', 'NANO')):
            line = (f"UNO,{i+1},{(i+1)*1000},{'NA' if missing_distance else 20+i%10},NA,NA,100,1" if origin == 'UNO'
                    else f'NANO,{i+1},{(i+1)*1000},NA,{pattern[i%10]},0,NA,NA')
            rows.append({**parse_sample(line, CONFIGS[origin]), 'id': i*2+j+1, 'captureId': origin,
                         'receivedAt': timestamp(BASE + i*1000+500+j*100), 'enabled': CONFIGS[origin]['enabled']})
    return rows


def make_trial(store, repo, partition='train', scenario='zona_vacia', seconds=10, reviewed=True, source='simulated'):
    session = repo.create_session({'name': 'PRUEBA SIMULADA', 'responsible': 'Prueba automatizada', 'partition': partition,
                                   'source': source, 'conditions': 'Caso sintetico exclusivo de pruebas', 'notes': ''})
    trial = repo.create_trial(session['id'], SCENARIO_BY_ID[scenario], '')
    captures = {}
    for origin in ('UNO', 'NANO'):
        capture = store.create_capture(origin, CONFIGS[origin])
        captures[origin] = capture
        repo.link(trial['id'], origin, capture)
    for row in readings(seconds):
        store.add_sample(captures[row['origin']], row, row['enabled'], row['receivedAt'])
    for capture in captures.values():
        store.end_capture(capture, 'stopped', 'simulated_test')
    with store.access(True) as db:
        db.execute('UPDATE captures SET started_at=?,ended_at=? WHERE capture_id IN (?,?)',
                   (timestamp(BASE), timestamp(BASE+seconds*1000), *captures.values()))
    repo.update_trial(trial['id'], status='completed', reviewed=int(reviewed), started_at=timestamp(BASE),
                      ended_at=timestamp(BASE+seconds*1000), analysis_state='processing')
    analyze_trial(store, repo, trial['id'])
    return session, repo.trial(trial['id'])


def test_window_features_and_digital_transitions():
    result = extract_window(readings(), BASE, BASE+10000, CONFIGS)
    assert result['eligible'] and result['reasons'] == []
    features = result['features']
    assert features['distance_mean_cm'] == 24.5
    assert features['distance_min_cm'] == 20
    assert features['distance_std_cm'] == pytest.approx(math.sqrt(8.25))
    assert features['distance_valid_fraction'] == 1
    assert features['pir_rising_edges'] == 3
    assert features['pir_high_fraction'] == 0.5
    assert features['radar_rising_edges'] == 0
    assert features['sound_high_fraction'] == 1
    assert set(features) == set(FEATURES) and len(features) == 10


def test_no_echo_is_not_zero_and_does_not_remove_empty_zone():
    result = extract_window(readings(missing_distance=True), BASE, BASE+10000, CONFIGS)
    assert result['eligible']
    for key in ('distance_mean_cm', 'distance_min_cm', 'distance_std_cm'):
        assert result['features'][key] is None
    assert result['features']['distance_valid_fraction'] == 0


def test_eight_rows_allowed_but_short_burst_and_missing_signals_rejected():
    rows = [row for row in readings() if row['sequence'] not in (3, 7)]
    assert extract_window(rows, BASE, BASE+10000, CONFIGS)['eligible']
    few = [row for row in readings() if row['sequence'] < 8]
    assert 'insufficient_rows_UNO' in extract_window(few, BASE, BASE+10000, CONFIGS)['reasons']
    burst = readings()
    for i, row in enumerate(burst):
        row['receivedAt'] = timestamp(BASE+i*10)
    assert 'reception_gap_UNO' in extract_window(burst, BASE, BASE+10000, CONFIGS)['reasons']
    missing = readings()
    for row in missing:
        if row['origin'] == 'UNO' and row['sequence'] < 4:
            row['lux'] = None
    assert 'insufficient_lux' in extract_window(missing, BASE, BASE+10000, CONFIGS)['reasons']


def test_duplicate_and_configuration_changes_are_flagged():
    rows = readings()
    rows.insert(1, rows[0])
    result = extract_window(rows, BASE, BASE+10000, CONFIGS)
    assert not result['eligible'] and 'duplicate_or_out_of_order' in result['reasons']
    rows = readings()
    rows[0]['enabled'] = {**rows[0]['enabled'], 'hc': False}
    assert 'sensor_configuration_changed' in extract_window(rows, BASE, BASE+10000, CONFIGS)['reasons']


def test_common_interval_nonoverlap_partial_tail_and_idempotent_analysis(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    repo = ExperimentStore(store)
    try:
        _, trial = make_trial(store, repo, seconds=25)
        assert trial['windowCount'] == 2 and trial['eligibleCount'] == 2
        assert trial['analysisSummary']['trailingSeconds'] == 5
        with store.access() as db:
            rows = db.execute('SELECT * FROM observations ORDER BY window_index').fetchall()
            assert rows[0]['ended_at'] == rows[1]['started_at']
        before = [dict(row) for row in rows]
        analyze_trial(store, repo, trial['id'])
        with store.access() as db:
            assert [dict(row) for row in db.execute('SELECT * FROM observations ORDER BY window_index')] == before
    finally:
        store.close()


def test_whole_trial_excluded_after_mask_change_or_interruption(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    repo = ExperimentStore(store)
    try:
        _, trial = make_trial(store, repo, seconds=20)
        with store.access(True) as db:
            db.execute('UPDATE samples SET enabled_json=? WHERE id=1', (json.dumps({**CONFIGS['UNO']['enabled'], 'sound': False}),))
        analyze_trial(store, repo, trial['id'])
        assert repo.trial(trial['id'])['eligibleCount'] == 0
        repo.update_trial(trial['id'], status='interrupted', reviewed=0)
        analyze_trial(store, repo, trial['id'])
        with store.access() as db:
            assert all('interrupted_trial' in json.loads(row[0]) for row in db.execute('SELECT reasons_json FROM observations'))
            assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == 40
    finally:
        store.close()


def test_export_sources_hashes_missing_values_and_reproduction(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    repo = ExperimentStore(store)
    try:
        train_session, train = make_trial(store, repo, seconds=20)
        test_session, test = make_trial(store, repo, partition='test', scenario='acercamientos_repetidos', seconds=10)
        for session in (train_session, test_session):
            repo.close_session(session['id'])
        sessions = [train_session['id'], test_session['id']]
        with export_dataset(store, repo, sessions) as file, zipfile.ZipFile(file) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            assert manifest['source'] == 'simulated' and not manifest['minimumMet'] and manifest['partial']
            assert manifest['counts'] == {'train': 2, 'test': 1}
            assert all(hashlib.sha256(archive.read(name)).hexdigest() == digest for name, digest in manifest['sha256'].items())
            assert all(len(archive.read(name)) == size for name, size in manifest['sizesBytes'].items())
            train_rows = list(csv.DictReader(io.StringIO(archive.read('train.csv').decode())))
            test_rows = list(csv.DictReader(io.StringIO(archive.read('test.csv').decode())))
            assert {row['session_id'] for row in train_rows}.isdisjoint(row['session_id'] for row in test_rows)
            assert train_rows[0]['label'] == 'normal' and test_rows[0]['label'] == 'anomalo'
            assert train_rows[0]['distance_mean_cm'] == '24.5'
            dictionary = json.loads(archive.read('dictionary.json'))
            assert 'label' not in dictionary['featureColumns'] and 'session_id' not in dictionary['featureColumns']
            assert sum(name.startswith('captures/') for name in archive.namelist()) == 4
        with export_dataset(store, repo, sessions) as file, zipfile.ZipFile(file) as archive:
            assert json.loads(archive.read('manifest.json'))['sha256'] == manifest['sha256']
        assert repo.summary()['real'] == {'train': 0, 'test': 0}
    finally:
        store.close()


def test_export_rejects_open_sessions_and_mixed_provenance(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    repo = ExperimentStore(store)
    try:
        a, _ = make_trial(store, repo)
        b, _ = make_trial(store, repo, source='real')  # Solo fixture: verifica el contrato de separacion.
        with pytest.raises(BackendError):
            export_dataset(store, repo, [a['id']])
        repo.close_session(a['id']); repo.close_session(b['id'])
        with pytest.raises(ValidationError):
            export_dataset(store, repo, [a['id'], b['id']])
    finally:
        store.close()


def test_common_interval_excludes_early_board_rows_and_keeps_independent_device_clocks(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    repo = ExperimentStore(store)
    try:
        _, trial = make_trial(store, repo, seconds=25)
        with store.access(True) as db:
            db.execute('UPDATE captures SET started_at=?,ended_at=? WHERE capture_id=?',
                       (timestamp(BASE+5000), timestamp(BASE+20000), trial['captures']['NANO']))
            db.execute('UPDATE samples SET time_ms=time_ms+900000 WHERE origin=?', ('NANO',))
        analyze_trial(store, repo, trial['id'])
        result = repo.trial(trial['id'])
        assert result['windowCount'] == result['eligibleCount'] == 1
        assert result['analysisSummary']['durationSeconds'] == 15
        assert result['analysisSummary']['trailingSeconds'] == 5
        assert result['analysisSummary']['commonStartedAt'] == timestamp(BASE+5000)
        assert result['analysisSummary']['coverage']['pir']['available'] == 10
    finally:
        store.close()


def test_clock_regression_and_unconfirmed_scenario_preserve_but_exclude_originals(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    repo = ExperimentStore(store)
    try:
        _, trial = make_trial(store, repo, seconds=20, reviewed=False)
        assert trial['eligibleCount'] == 0 and trial['windowCount'] == 2
        repo.update_trial(trial['id'], reviewed=1)
        with store.access(True) as db:
            db.execute('UPDATE samples SET received_at=? WHERE id=9', (timestamp(BASE+100),))
        analyze_trial(store, repo, trial['id'])
        assert repo.trial(trial['id'])['eligibleCount'] == 0
        assert 'clock_regression' in repo.trial(trial['id'])['analysisSummary']['sourceIssues']
        assert store.capture(trial['captures']['UNO'])['sampleCount'] == 20
    finally:
        store.close()
