"""Caracteristicas puras y exportacion: nunca entrena ni rellena mediciones."""
from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import math
import tempfile
import zipfile

from .errors import BackendError, ValidationError
from .protocol import default_config
from .storage import utc_now
from .migrations import SCHEMA_VERSION

FEATURE_VERSION = 1
WINDOW_MS = 10000
MIN_ROWS = 8
MAX_GAP_MS = 3500
FEATURES = (
    'distance_mean_cm', 'distance_min_cm', 'distance_std_cm', 'distance_valid_fraction',
    'pir_high_fraction', 'pir_rising_edges', 'radar_high_fraction', 'radar_rising_edges',
    'lux_mean', 'sound_high_fraction',
)
POLICY = {'version': FEATURE_VERSION, 'windowSeconds': 10, 'minimumRowsPerBoard': MIN_ROWS,
          'minimumValidValues': MIN_ROWS, 'maximumReceptionGapSeconds': 3.5,
          'overlap': False, 'interruptedTrials': 'excluded', 'missingDistance': 'NA; no imputation'}
META_COLUMNS = ('observation_id', 'session_id', 'trial_id', 'capture_uno_id', 'capture_nano_id',
                'scenario', 'window_start', 'window_end', 'label')


def milliseconds(value):
    if not isinstance(value, str):
        raise ValueError('Timestamp invalido.')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp sin zona horaria.')
    return round(parsed.timestamp() * 1000)


def timestamp(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def extract_window(rows, start, end, configs, base_reasons=()):
    """Consume un iterable, en orden de recepcion, con acumuladores de memoria fija."""
    reasons = set(base_reasons)
    boards = {origin: {'rows': 0, 'firstSampleId': None, 'lastSampleId': None, 'lastTime': start,
                       'lastSequence': 0, 'lastDevice': -1, 'maxGapMs': 0} for origin in ('UNO', 'NANO')}
    counts = Counter()
    highs = Counter()
    edges = Counter()
    previous = {}
    mean_distance = m2_distance = 0.0
    minimum_distance = None
    mean_lux = 0.0
    fields = {'pir': ('NANO', 'pir'), 'radar': ('NANO', 'radar'), 'sound': ('UNO', 'sound')}
    for row in rows:
        origin = row.get('origin')
        if origin not in boards:
            reasons.add('unknown_origin')
            continue
        try:
            received = milliseconds(row['receivedAt'])
        except (ValueError, TypeError, KeyError):
            reasons.add('invalid_timestamp')
            continue
        if not start <= received < end:
            reasons.add('outside_window')
            continue
        board = boards[origin]
        seq, device = row.get('sequence'), row.get('timeMs')
        if type(seq) is not int or type(device) is not int or seq <= board['lastSequence'] or device < board['lastDevice']:
            reasons.add('duplicate_or_out_of_order')
            continue
        if received < board['lastTime']:
            reasons.add('clock_regression')
        board['maxGapMs'] = max(board['maxGapMs'], received - board['lastTime'])
        board['lastTime'], board['lastSequence'], board['lastDevice'] = received, seq, device
        board['rows'] += 1
        if board['firstSampleId'] is None:
            board['firstSampleId'] = row.get('id')
        board['lastSampleId'] = row.get('id')
        expected = configs.get(origin, {}).get('enabled', {})
        if row.get('enabled') != expected or expected != default_config(origin)['enabled']:
            reasons.add('sensor_configuration_changed')
        if origin == 'UNO':
            distance = row.get('distanceCm')
            if finite(distance) and 2 <= distance <= 400:
                counts['distance'] += 1
                delta = distance - mean_distance
                mean_distance += delta / counts['distance']
                m2_distance += delta * (distance - mean_distance)
                minimum_distance = distance if minimum_distance is None else min(minimum_distance, distance)
            elif distance is not None:
                reasons.add('invalid_distance')
            lux = row.get('lux')
            if finite(lux) and lux >= 0:
                counts['lux'] += 1
                mean_lux += (lux - mean_lux) / counts['lux']
            elif lux is not None:
                reasons.add('invalid_lux')
        for field, (owner, key) in fields.items():
            if owner != origin:
                continue
            value = row.get(key)
            if type(value) is int and value in (0, 1):
                counts[field] += 1
                highs[field] += value
                prior = previous.get(field)
                if prior and prior[0] == 0 and value == 1 and seq == prior[2] + 1 and 0 <= received - prior[1] <= MAX_GAP_MS:
                    edges[field] += 1
                previous[field] = (value, received, seq)
            else:
                previous.pop(field, None)
                if value is not None:
                    reasons.add(f'invalid_{field}')
    for origin, board in boards.items():
        board['maxGapMs'] = max(board['maxGapMs'], end - board['lastTime'])
        if board['rows'] < MIN_ROWS:
            reasons.add(f'insufficient_rows_{origin}')
        if board['maxGapMs'] > MAX_GAP_MS:
            reasons.add(f'reception_gap_{origin}')
        for key in ('lastTime', 'lastSequence', 'lastDevice'):
            board.pop(key)
    for field in ('lux', 'sound', 'pir', 'radar'):
        if counts[field] < MIN_ROWS:
            reasons.add(f'insufficient_{field}')
    fraction = lambda field: highs[field] / counts[field] if counts[field] else None
    features = dict(zip(FEATURES, (
        mean_distance if counts['distance'] else None, minimum_distance,
        math.sqrt(max(0, m2_distance / counts['distance'])) if counts['distance'] else None,
        counts['distance'] / boards['UNO']['rows'] if boards['UNO']['rows'] else 0,
        fraction('pir'), edges['pir'], fraction('radar'), edges['radar'],
        mean_lux if counts['lux'] else None, fraction('sound'),
    )))
    return {'features': features, 'quality': {'boards': boards, 'available': dict(counts)},
            'reasons': sorted(reasons), 'eligible': not reasons}


def source_issues(store, trial):
    reasons = set()
    for origin, capture in trial['captureDetails'].items():
        if capture['config'].get('enabled') != default_config(origin)['enabled']:
            reasons.add('sensor_configuration_changed')
        last_time, last_sequence, last_device, cursor = None, 0, -1, 0
        while True:
            page = store.page('samples', capture_id=capture['id'], after_id=cursor, limit=500)
            if not page['items']:
                break
            for row in page['items']:
                try:
                    value = milliseconds(row['receivedAt'])
                    if last_time is not None and value < last_time:
                        reasons.add('clock_regression')
                    last_time = value
                except (ValueError, TypeError):
                    reasons.add('invalid_timestamp')
                if row['sequence'] <= last_sequence or row['timeMs'] < last_device:
                    reasons.add('duplicate_or_out_of_order')
                last_sequence, last_device = row['sequence'], row['timeMs']
                if row['origin'] != origin or row['enabled'] != capture['config']['enabled']:
                    reasons.add('sensor_configuration_changed')
            cursor = page['nextCursor']
    return reasons


def sample_stream(store, capture_ids, start, end):
    received, row_id = '', 0
    marks = ','.join('?' for _ in capture_ids)
    while True:
        with store.access() as db:
            rows = db.execute(f'''SELECT * FROM samples WHERE capture_id IN ({marks}) AND received_at>=? AND received_at<?
                 AND (received_at>? OR (received_at=? AND id>?)) ORDER BY received_at,id LIMIT 500''',
                 (*capture_ids, timestamp(start), timestamp(end), received, received, row_id)).fetchall()
        if not rows:
            return
        for row in rows:
            sample = store._sample(row)
            try:
                milliseconds(sample['receivedAt'])
            except ValueError:
                continue  # source_issues ya excluye el ensayo completo, sin perder sus fuentes.
            yield sample
        received, row_id = rows[-1]['received_at'], rows[-1]['id']


class AnalysisCancelled(Exception):
    pass


def analyze_trial(store, repository, trial_id, cancelled=lambda: False):
    trial = repository.trial(trial_id)
    captures = trial['captureDetails']
    reasons = source_issues(store, trial)
    if trial['status'] != 'completed':
        reasons.add('interrupted_trial')
    if trial['reviewed'] is not True:
        reasons.add('scenario_not_confirmed')
    with store.access(True) as db:
        db.execute('DELETE FROM observations WHERE trial_id=?', (trial_id,))
    summary = {'rawCounts': {origin: capture['sampleCount'] for origin, capture in captures.items()},
               'sourceIssues': sorted(reasons), 'windowSeconds': 10, 'featureVersion': FEATURE_VERSION,
               'windowCount': 0, 'eligibleCount': 0, 'durationSeconds': 0, 'trailingSeconds': 0, 'exclusions': {},
               'coverage': {key: {'available': 0, 'total': 0} for key in ('distance', 'lux', 'sound', 'pir', 'radar')}}
    if set(captures) != {'UNO', 'NANO'}:
        if trial['status'] == 'completed':
            raise ValidationError('El ensayo completo no tiene ambas capturas.')
        repository.update_trial(trial_id, analysis_summary_json=json.dumps(summary), analysis_state='ready', analysis_error=None)
        return
    if any(not capture['endedAt'] for capture in captures.values()):
        raise BackendError('Las capturas deben estar cerradas antes de analizar.')
    start = max(milliseconds(capture['startedAt']) for capture in captures.values())
    end = min(milliseconds(capture['endedAt']) for capture in captures.values())
    duration = max(0, end - start)
    window_count = duration // WINDOW_MS
    summary.update(commonStartedAt=timestamp(start), commonEndedAt=timestamp(end),
                   durationSeconds=duration / 1000, trailingSeconds=(duration % WINDOW_MS) / 1000)
    source = iter(sample_stream(store, list(trial['captures'].values()), start, end))
    current = next(source, None)
    exclusion_counts = Counter()
    configs = {origin: capture['config'] for origin, capture in captures.items()}
    for index in range(window_count):
        if cancelled():
            raise AnalysisCancelled()
        left, right = start + index * WINDOW_MS, start + (index + 1) * WINDOW_MS

        def rows_in_window():
            nonlocal current
            while current is not None and milliseconds(current['receivedAt']) < right:
                yield current
                current = next(source, None)

        observation = extract_window(rows_in_window(), left, right, configs, reasons)
        exclusion_counts.update(observation['reasons'])
        for field, coverage in summary['coverage'].items():
            origin = 'NANO' if field in ('pir', 'radar') else 'UNO'
            coverage['available'] += observation['quality']['available'].get(field, 0)
            coverage['total'] += observation['quality']['boards'][origin]['rows']
        with store.access(True) as db:
            db.execute('''INSERT INTO observations(observation_id,trial_id,feature_version,window_index,started_at,ended_at,
                       features_json,quality_json,reasons_json,eligible) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                       (f'{trial_id}:{FEATURE_VERSION}:{index}', trial_id, FEATURE_VERSION, index, timestamp(left), timestamp(right),
                        json.dumps(observation['features'], allow_nan=False), json.dumps(observation['quality']),
                        json.dumps(observation['reasons']), int(observation['eligible'])))
        summary['windowCount'] += 1
        summary['eligibleCount'] += int(observation['eligible'])
    summary['exclusions'] = dict(exclusion_counts)
    for coverage in summary['coverage'].values():
        coverage.update(missing=coverage['total'] - coverage['available'],
                        fraction=coverage['available'] / coverage['total'] if coverage['total'] else None)
    repository.update_trial(trial_id, analysis_summary_json=json.dumps(summary), analysis_state='ready', analysis_error=None)


def observation_stream(store, session_ids):
    marks = ','.join('?' for _ in session_ids)
    ordinal, index = 0, -1
    while True:
        with store.access() as db:
            rows = db.execute(f'''SELECT o.*,t.ordinal AS trial_ordinal,t.session_id,t.scenario,t.expected_label,
                 s.partition_name,s.source FROM observations o JOIN trials t ON t.trial_id=o.trial_id
                 JOIN collection_sessions s ON s.session_id=t.session_id
                 WHERE s.session_id IN ({marks}) AND t.analysis_state='ready'
                 AND (t.ordinal>? OR (t.ordinal=? AND o.window_index>?))
                 ORDER BY t.ordinal,o.window_index LIMIT 500''', (*session_ids, ordinal, ordinal, index)).fetchall()
        if not rows:
            return
        yield from rows
        ordinal, index = rows[-1]['trial_ordinal'], rows[-1]['window_index']


def export_dataset(store, repository, session_ids):
    """Crea un ZIP temporal. El llamador debe cerrarlo incluso si se cancela la descarga."""
    session_ids = list(dict.fromkeys(session_ids))
    if not session_ids:
        raise ValidationError('Selecciona al menos una sesion cerrada.')
    sessions = [repository.session(item) for item in session_ids]
    if any(item['status'] != 'closed' for item in sessions):
        raise BackendError('Solo se exportan sesiones cerradas y revisadas.')
    if len({item['source'] for item in sessions}) != 1:
        raise ValidationError('Exporta datos reales y simulados en paquetes separados.')
    source_kind = sessions[0]['source']
    trials = []
    for session_id in session_ids:
        cursor = 0
        while True:
            page = repository.trials(session_id, cursor, 100)
            if not page['items']:
                break
            trials.extend(page['items'])
            cursor = page['nextCursor']
    if any(item['analysisState'] != 'ready' or item['reviewed'] is None for item in trials):
        raise BackendError('Hay ensayos sin confirmar o analizar.')
    links = {trial['id']: trial['captures'] for trial in trials}
    counts = {'train': 0, 'test': 0}
    balance = Counter()
    hashes, sizes = {}, {}
    temporary = tempfile.TemporaryFile('w+b')
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            def write_text(name, chunks):
                digest = hashlib.sha256()
                size = 0
                with archive.open(name, 'w') as target:
                    for text in chunks:
                        data = text.encode('utf-8')
                        digest.update(data)
                        size += len(data)
                        target.write(data)
                hashes[name] = digest.hexdigest()
                sizes[name] = size

            def csv_chunks(header, rows):
                buffer = io.StringIO(newline='')
                writer = csv.writer(buffer, lineterminator='\r\n')
                for values in (header,):
                    writer.writerow(values)
                yield buffer.getvalue()
                for values in rows:
                    buffer.seek(0); buffer.truncate(0)
                    writer.writerow(['NA' if value is None else value for value in values])
                    yield buffer.getvalue()

            for partition in ('train', 'test'):
                def feature_rows(partition=partition):
                    for row in observation_stream(store, session_ids):
                        if not row['eligible'] or row['partition_name'] != partition:
                            continue
                        counts[partition] += 1
                        balance[(partition, row['scenario'])] += 1
                        captures = links[row['trial_id']]
                        metadata = [row['observation_id'], row['session_id'], row['trial_id'], captures.get('UNO'), captures.get('NANO'),
                                    row['scenario'], row['started_at'], row['ended_at'], row['expected_label']]
                        features = json.loads(row['features_json'])
                        yield metadata + [features[name] for name in FEATURES]
                write_text(f'{partition}.csv', csv_chunks((*META_COLUMNS, *FEATURES), feature_rows()))

            def quality_rows():
                for row in observation_stream(store, session_ids):
                    yield [row['observation_id'], row['session_id'], row['trial_id'], row['started_at'], row['ended_at'],
                           row['eligible'], row['reasons_json'], row['quality_json']]
            write_text('quality.csv', csv_chunks(('observation_id', 'session_id', 'trial_id', 'window_start', 'window_end',
                                                 'eligible', 'reasons', 'quality'), quality_rows()))
            for trial in trials:
                for capture_id in trial['captures'].values():
                    write_text(f'captures/{capture_id}.csv', store.export('samples', capture_id=capture_id))
            dictionary = {'featureColumns': FEATURES, 'metadataColumns': META_COLUMNS, 'labels': ['normal', 'anomalo'],
                          'units': {'distance_mean_cm': 'cm', 'distance_min_cm': 'cm', 'distance_std_cm': 'cm', 'lux_mean': 'lux',
                                    'pir_rising_edges': 'observed 0->1 transitions', 'radar_rising_edges': 'observed 0->1 transitions'},
                          'fractions': '0..1; denominator is available readings, except distance availability uses UNO rows',
                          'definitions': {
                            'distance_mean_cm': 'Arithmetic mean of valid 2..400 cm distances.',
                            'distance_min_cm': 'Minimum valid distance.',
                            'distance_std_cm': 'Population standard deviation; zero with one valid reading.',
                            'distance_valid_fraction': 'Valid distances / valid UNO rows in the window.',
                            'pir_high_fraction': 'Available PIR readings equal to one / available PIR readings.',
                            'pir_rising_edges': 'Observed adjacent 0->1 changes inside the window; no interpolation.',
                            'radar_high_fraction': 'Available radar readings equal to one / available radar readings.',
                            'radar_rising_edges': 'Observed adjacent 0->1 changes inside the window; no interpolation.',
                            'lux_mean': 'Arithmetic mean of available nonnegative lux readings.',
                            'sound_high_fraction': 'Available raw sound DO readings equal to one / available readings; not dB.',
                            'observation_id': 'Deterministic trial_id:feature_version:zero_based_window_index.',
                            'session_id': 'Acquisition group; belongs to a single partition in manifest.',
                            'trial_id': 'One human-reviewed scenario; raw capture IDs identify sources.',
                            'window_start': 'Inclusive Raspberry reception UTC timestamp.',
                            'window_end': 'Exclusive Raspberry reception UTC timestamp.',
                            'label': 'Human-confirmed scenario class; never a model input.'},
                          'missing': 'NA/null is not zero. Future imputation must be fitted only on train.', 'policy': POLICY}
            write_text('dictionary.json', [json.dumps(dictionary, ensure_ascii=False, indent=2, sort_keys=True)])
            readme = ('Dataset Grupo C.\nOrigen: ' + source_kind + '\n'
                      'Una observacion = 10 segundos, sin superposicion, sobre recepcion UTC de Raspberry.\n'
                      'Las columnas featureColumns de dictionary.json son las unicas entradas propuestas al modelo.\n'
                      'No usar identificadores, escenario, particion, timestamps ni etiqueta como entradas.\n'
                      'No dividir ventanas de una misma sesion entre conjuntos. No ajustar usando test.\n'
                      'NA conserva lecturas ausentes; no hay imputacion, escalado ni modelo entrenado.\n'
                      'Las capturas originales estan en captures/; quality.csv conserva exclusiones.\n'
                      'Reexportar estas sesiones cerradas reproduce los CSV y sus hashes, no la hora de generacion del ZIP.\n'
                      'Las mediciones simuladas nunca acreditan el requisito de observaciones reales.\n')
            write_text('README.txt', [readme])
            from .experiments import SCENARIOS
            manifest = {'schemaVersion': SCHEMA_VERSION, 'featureVersion': FEATURE_VERSION, 'generatedAt': utc_now(), 'source': source_kind,
                        'scenarios': SCENARIOS,
                        'sessions': sessions, 'trials': trials, 'policy': POLICY, 'counts': counts,
                        'balanceByScenario': [{'partition': key[0], 'scenario': key[1], 'count': value} for key, value in sorted(balance.items())],
                        'minimumTestObservations': 100, 'minimumMet': source_kind == 'real' and counts['test'] >= 100,
                        'targetMet': source_kind == 'real' and all(balance[(part, scenario)] >= target
                          for part, target in (('train', 50), ('test', 25))
                          for scenario in ('zona_vacia', 'paso_breve', 'acercamientos_repetidos', 'permanencia_proxima')),
                        'sha256': hashes, 'sizesBytes': sizes}
            manifest['partial'] = not manifest['targetMet']
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
        temporary.seek(0)
        return temporary
    except Exception:
        temporary.close()
        raise
