"""Ventanas de inferencia separadas de las observaciones etiquetadas."""
import json
import logging
import threading

from .dataset import WINDOW_MS, extract_window, milliseconds, sample_stream, timestamp
from .ml_runtime import ModelRuntime
from .storage import utc_now

logger = logging.getLogger(__name__)


class Monitoring:
    def __init__(self, service, access):
        self.service, self.access, self.store = service, access, service.store
        self.runtime = ModelRuntime(service.settings.model_file, allow_simulated=service.experiments.simulated)
        self.run_id, self.left, self.latest = None, None, None
        self.error = ''
        self.worker = threading.Thread(target=self._run, name='ml-inference', daemon=True)

    def status(self):
        model = self.runtime.status()
        active = self.access.active
        latest = self.latest if self.run_id == self.access.run_id and active else None
        age = max(0, milliseconds(utc_now()) - milliseconds(latest['endedAt'])) if latest else None
        state = ('inactive' if not active else 'error' if self.error else model['state'] if model['state'] != 'ready'
                 else 'waiting' if not latest else 'stale' if age > 15000 else 'ready' if latest['label'] else 'insufficient_data')
        return {**model, 'modelState': model['state'], 'state': state, 'processingError': self.error,
                'active': active, 'latest': latest, 'ageMs': age}

    @staticmethod
    def prediction(row):
        return {'id': row['id'], 'runId': row['run_id'], 'modelId': row['model_id'], 'unoCapture': row['uno_capture'],
                'nanoCapture': row['nano_capture'], 'startedAt': row['started_at'], 'endedAt': row['ended_at'],
                'createdAt': row['created_at'], 'label': row['label'], 'score': row['score'],
                'features': json.loads(row['features_json']), 'quality': json.loads(row['quality_json']),
                'reasons': json.loads(row['reasons_json'])}

    def predictions(self, after_id=0, limit=20):
        with self.store.access() as db:
            rows = db.execute('SELECT * FROM ml_predictions WHERE (?=0 OR id<?) ORDER BY id DESC LIMIT ?',
                              (after_id, after_id, limit)).fetchall()
        return {'items': [self.prediction(row) for row in rows], 'nextCursor': rows[-1]['id'] if rows else after_id}

    def tick(self):
        if not self.access.active:
            return
        run_id = self.access.run_id
        if run_id != self.run_id:
            self.run_id, self.left = run_id, milliseconds(self.access.started_at)
            self.latest, self.error = None, ''
        states = self.service.snapshots()
        if self.access.core_issue(states):
            return
        right = self.left + WINDOW_MS
        # Cada actor guarda sus filas secuencialmente antes de actualizar latestSample.
        # Una muestra posterior al borde garantiza que las anteriores ya estan confirmadas.
        watermark = min(milliseconds(row['lastReceivedAt']) for row in states)
        if watermark < right:
            return
        if watermark - right > 300000:
            self.left = self.left + ((watermark - self.left) // WINDOW_MS - 1) * WINDOW_MS
            right = self.left + WINDOW_MS
            self.store.incident('SYSTEM', 'ML_LAG', 'Inferencia atrasada; se recupera una ventana reciente, conservando las fuentes.')
        capture_ids = dict(self.access.captures)
        configs = {row['origin']: row['config'] for row in states}
        result = extract_window(sample_stream(self.store, list(capture_ids.values()), self.left, right), self.left, right, configs)
        label, score = None, None
        if self.runtime.model is None or self.runtime.state != 'ready':
            result['reasons'].append('model_unavailable')
        elif result['eligible']:
            try:
                predicted = self.runtime.model.predict(result['features'])
                label, score = predicted['label'], predicted['score']
            except (ValueError, OverflowError):
                result['reasons'].append('model_error')
        if not self.access.lock.acquire(blocking=False):
            return
        try:
            if not self.access.active or self.access.run_id != run_id or self.access.core_issue():
                return
            with self.store.access(True) as db:
                db.execute('''INSERT OR IGNORE INTO ml_predictions(run_id,model_id,uno_capture,nano_capture,started_at,ended_at,
                    created_at,label,score,features_json,quality_json,reasons_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (run_id, self.runtime.model.id if self.runtime.model else None, capture_ids['UNO'], capture_ids['NANO'],
                     timestamp(self.left), timestamp(right), utc_now(), label, score, json.dumps(result['features'], allow_nan=False),
                     json.dumps(result['quality']), json.dumps(sorted(set(result['reasons'])))))
                row = db.execute('SELECT * FROM ml_predictions WHERE run_id=? AND started_at=?', (run_id, timestamp(self.left))).fetchone()
                self.latest = self.prediction(row)
            self.left = right
            self.error = ''
        finally:
            self.access.lock.release()

    def _run(self):
        while not self.access.stopping.wait(0.2):
            try:
                self.tick()
            except Exception:
                self.error = 'No se pudo procesar ML. La autorizacion conserva su regla independiente.'
                logger.error('Fallo en procesamiento ML; se conservan las fuentes.')
                self.access.stopping.wait(1)
