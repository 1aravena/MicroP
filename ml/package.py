"""Lectura validada de paquetes propios. No extrae rutas del ZIP al disco."""
import csv
import hashlib
import io
import json
import math
import zipfile
import uuid

from backend.dataset import FEATURES, FEATURE_VERSION, META_COLUMNS, milliseconds
from backend.experiments import SCENARIO_BY_ID


class DatasetPackage:
    def __init__(self, path, *, allow_simulated=False):
        self.archive = zipfile.ZipFile(path)
        try:
            raw = self.archive.read('manifest.json')
            self.manifest = json.loads(raw)
            self.manifest_hash = hashlib.sha256(raw).hexdigest()
            data = self.manifest
            if data.get('schemaVersion') not in (2, 3) or data.get('featureVersion') != FEATURE_VERSION:
                raise ValueError('Version de dataset incompatible.')
            if data.get('source') not in ('real', 'simulated') or (data['source'] == 'simulated' and not allow_simulated):
                raise ValueError('El paquete es simulado. Solo se permite para pruebas explicitas con --allow-simulated.')
            self.sessions = {item['id']: item for item in data['sessions']}
            self.trials = {item['id']: item for item in data['trials']}
            if len(self.sessions) != len(data['sessions']) or len(self.trials) != len(data['trials']):
                raise ValueError('Identificadores de sesion o ensayo duplicados.')
            for identifier in (*self.sessions, *self.trials):
                if str(uuid.UUID(identifier)) != identifier:
                    raise ValueError('Identificador de sesion o ensayo invalido.')
            for session in self.sessions.values():
                if session['status'] != 'closed' or session['source'] != data['source'] or session['partition'] not in ('train', 'test'):
                    raise ValueError('Sesion abierta, mezclada o sin particion valida.')
            capture_owners = {}
            for trial in self.trials.values():
                if trial['sessionId'] not in self.sessions:
                    raise ValueError('Ensayo sin sesion identificable.')
                for capture in trial['captures'].values():
                    if str(uuid.UUID(capture)) != capture:
                        raise ValueError('Identificador de captura invalido.')
                    if capture in capture_owners:
                        raise ValueError('Captura compartida entre ensayos.')
                    capture_owners[capture] = trial['id']
            for required in ('train.csv', 'test.csv', 'quality.csv', 'dictionary.json', 'README.txt'):
                if required not in data['sha256']:
                    raise ValueError('Faltan archivos verificables del paquete.')
            if len(set(self.archive.namelist())) != len(self.archive.namelist()):
                raise ValueError('Entradas duplicadas en el ZIP.')
            for name, digest in data['sha256'].items():
                actual = hashlib.sha256()
                size = 0
                with self.archive.open(name) as file:
                    while block := file.read(65536):
                        actual.update(block)
                        size += len(block)
                if actual.hexdigest() != digest or ('sizesBytes' in data and data['sizesBytes'].get(name) != size):
                    raise ValueError('Hash o tamano de archivo inconsistente.')
        except Exception:
            self.archive.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.archive.close()

    def read(self, partition):
        result, seen, intervals = [], set(), {}
        with self.archive.open(f'{partition}.csv') as raw, io.TextIOWrapper(raw, encoding='utf-8-sig', newline='') as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != list(META_COLUMNS) + list(FEATURES):
                raise ValueError('Columnas incompatibles con las diez caracteristicas version 1.')
            for row in reader:
                if row['observation_id'] in seen:
                    raise ValueError('Observacion repetida.')
                seen.add(row['observation_id'])
                session, trial = self.sessions.get(row['session_id']), self.trials.get(row['trial_id'])
                if not session or session['partition'] != partition or not trial or trial['sessionId'] != session['id']:
                    raise ValueError('Observacion fuera de su sesion o particion.')
                scenario = SCENARIO_BY_ID.get(row['scenario'])
                if (not scenario or row['label'] != scenario['label'] or row['scenario'] != trial['scenario']
                        or trial['status'] != 'completed' or trial['reviewed'] is not True or trial['analysisState'] != 'ready'
                        or row['capture_uno_id'] != trial['captures'].get('UNO') or row['capture_nano_id'] != trial['captures'].get('NANO')):
                    raise ValueError('Etiqueta, revision o fuente incompatible con el ensayo.')
                left, right = milliseconds(row['window_start']), milliseconds(row['window_end'])
                index = int(row['observation_id'].rsplit(':', 1)[-1])
                common_start = max(milliseconds(item['startedAt']) for item in trial['captureDetails'].values())
                common_end = min(milliseconds(item['endedAt']) for item in trial['captureDetails'].values())
                if (right - left != 10000 or index < 0 or row['observation_id'] != f"{trial['id']}:1:{index}"
                        or left != common_start + index * 10000 or right > common_end):
                    raise ValueError('Ventana distinta de diez segundos.')
                intervals.setdefault(row['trial_id'], []).append((left, right))
                values = []
                for name in FEATURES:
                    text = row[name]
                    if text == 'NA' and name in FEATURES[:3]:
                        values.append(float('nan'))
                    else:
                        value = float(text)
                        if not math.isfinite(value):
                            raise ValueError('Caracteristica no finita.')
                        values.append(value)
                result.append({'metadata': {name: row[name] for name in META_COLUMNS}, 'features': values,
                               'y': int(row['label'] == 'anomalo'), 'group': session['id']})
        for windows in intervals.values():
            windows.sort()
            if any(previous[1] > current[0] for previous, current in zip(windows, windows[1:])):
                raise ValueError('Ventanas superpuestas.')
        return result
