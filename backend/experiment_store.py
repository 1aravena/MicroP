"""Persistencia de ensayos sobre la misma conexion y transacciones de Store."""
import json
import uuid

from .errors import BackendError, NotFound
from .storage import utc_now


class ExperimentStore:
    def __init__(self, store):
        self.store = store

    def session(self, session_id):
        with self.store.access() as db:
            row = db.execute('SELECT * FROM collection_sessions WHERE session_id=?', (session_id,)).fetchone()
            if row is None:
                raise NotFound('Sesion no encontrada.')
            result = self.session_dict(row)
            result['trialCount'] = db.execute('SELECT COUNT(*) FROM trials WHERE session_id=?', (session_id,)).fetchone()[0]
            return result

    @staticmethod
    def session_dict(row):
        return {'id': row['session_id'], 'cursor': row['ordinal'], 'name': row['name'], 'responsible': row['responsible'],
                'partition': row['partition_name'], 'source': row['source'], 'conditions': row['conditions'], 'notes': row['notes'],
                'createdAt': row['created_at'], 'closedAt': row['closed_at'], 'status': row['status']}

    def sessions(self, after_id=0, limit=20):
        with self.store.access() as db:
            rows = db.execute('SELECT * FROM collection_sessions WHERE (?=0 OR ordinal<?) ORDER BY ordinal DESC LIMIT ?',
                              (after_id, after_id, limit)).fetchall()
            return {'items': [self.session_dict(row) for row in rows], 'nextCursor': rows[-1]['ordinal'] if rows else after_id}

    def create_session(self, values):
        session_id = str(uuid.uuid4())
        with self.store.access(True) as db:
            db.execute('''INSERT INTO collection_sessions(session_id,name,responsible,partition_name,source,conditions,notes,created_at)
                       VALUES(?,?,?,?,?,?,?,?)''', (session_id, values['name'], values['responsible'], values['partition'],
                       values['source'], values['conditions'], values.get('notes', ''), utc_now()))
        return self.session(session_id)

    def create_trial(self, session_id, scenario, notes):
        trial_id = str(uuid.uuid4())
        with self.store.access(True) as db:
            session = db.execute('SELECT status FROM collection_sessions WHERE session_id=?', (session_id,)).fetchone()
            if session is None:
                raise NotFound('Sesion no encontrada.')
            if session['status'] != 'open':
                raise BackendError('La sesion esta cerrada; crea otra para agregar ensayos.')
            db.execute('''INSERT INTO trials(trial_id,session_id,scenario,expected_label,notes,created_at,status)
                       VALUES(?,?,?,?,?,?,'prepared')''', (trial_id, session_id, scenario['id'], scenario['label'], notes, utc_now()))
        return self.trial(trial_id)

    def trial(self, trial_id):
        with self.store.access() as db:
            row = db.execute('SELECT * FROM trials WHERE trial_id=?', (trial_id,)).fetchone()
            if row is None:
                raise NotFound('Ensayo no encontrado.')
            result = self.trial_dict(row)
            links = db.execute('SELECT origin,capture_id FROM trial_captures WHERE trial_id=?', (trial_id,)).fetchall()
            result['captures'] = {row['origin']: row['capture_id'] for row in links}
            result['captureDetails'] = {row['origin']: self.store.capture(row['capture_id']) for row in links}
            counts = db.execute('SELECT COUNT(*),COALESCE(SUM(eligible),0) FROM observations WHERE trial_id=?', (trial_id,)).fetchone()
            result.update(windowCount=counts[0], eligibleCount=counts[1] if result['analysisState'] == 'ready' else 0)
            from .dataset import milliseconds
            end = result['endedAt'] or utc_now()
            elapsed = max(0, (milliseconds(end) - milliseconds(result['startedAt'])) / 1000) if result['startedAt'] else 0
            result.update(elapsedSeconds=elapsed, completeWindowsEstimate=int(elapsed // 10))
            return result

    @staticmethod
    def trial_dict(row):
        return {'id': row['trial_id'], 'cursor': row['ordinal'], 'sessionId': row['session_id'], 'scenario': row['scenario'],
                'expectedLabel': row['expected_label'], 'notes': row['notes'], 'createdAt': row['created_at'],
                'startedAt': row['started_at'], 'endedAt': row['ended_at'], 'status': row['status'], 'endReason': row['end_reason'],
                'reviewed': None if row['reviewed'] is None else bool(row['reviewed']), 'reviewedAt': row['reviewed_at'],
                'reviewNotes': row['review_notes'], 'analysisState': row['analysis_state'], 'analysisError': row['analysis_error'],
                'featureVersion': row['feature_version'], 'analysisSummary': json.loads(row['analysis_summary_json'])}

    def trials(self, session_id=None, after_id=0, limit=20):
        with self.store.access() as db:
            rows = db.execute('''SELECT * FROM trials WHERE (? IS NULL OR session_id=?) AND (?=0 OR ordinal<?)
                              ORDER BY ordinal DESC LIMIT ?''', (session_id, session_id, after_id, after_id, limit)).fetchall()
            # Una pagina acotada; los detalles se leen con el mismo bloqueo reentrante.
            return {'items': [self.trial(row['trial_id']) for row in rows], 'nextCursor': rows[-1]['ordinal'] if rows else after_id}

    def update_trial(self, trial_id, **values):
        allowed = {'status', 'started_at', 'ended_at', 'end_reason', 'reviewed', 'reviewed_at', 'review_notes', 'analysis_state', 'analysis_error', 'analysis_summary_json'}
        if not values or set(values) - allowed:
            raise ValueError('Campos de ensayo invalidos.')
        with self.store.access(True) as db:
            db.execute(f"UPDATE trials SET {','.join(key+'=?' for key in values)} WHERE trial_id=?", (*values.values(), trial_id))

    def link(self, trial_id, origin, capture_id):
        with self.store.access(True) as db:
            db.execute('INSERT INTO trial_captures(trial_id,origin,capture_id) VALUES(?,?,?)', (trial_id, origin, capture_id))

    def close_session(self, session_id):
        session = self.session(session_id)
        if session['status'] == 'closed':
            return session
        with self.store.access(True) as db:
            incomplete = db.execute('''SELECT COUNT(*) FROM trials WHERE session_id=?
                AND (status NOT IN ('completed','interrupted') OR reviewed IS NULL OR analysis_state!='ready')''', (session_id,)).fetchone()[0]
            if incomplete:
                raise BackendError('Termina, confirma y espera el analisis de todos los ensayos antes de cerrar la sesion.')
            db.execute("UPDATE collection_sessions SET status='closed',closed_at=? WHERE session_id=?", (utc_now(), session_id))
        return self.session(session_id)

    def pending(self):
        with self.store.access() as db:
            row = db.execute('''SELECT trial_id FROM trials WHERE status IN ('completed','interrupted')
                AND reviewed IS NOT NULL AND analysis_state='pending' ORDER BY ordinal LIMIT 1''').fetchone()
            return row['trial_id'] if row else None

    def summary(self):
        with self.store.access() as db:
            rows = db.execute('''SELECT s.partition_name,s.source,t.scenario,t.expected_label,
                   COUNT(o.observation_id) AS windows,COALESCE(SUM(o.eligible),0) AS eligible
                   FROM collection_sessions s JOIN trials t ON t.session_id=s.session_id
                   LEFT JOIN observations o ON o.trial_id=t.trial_id
                   WHERE t.analysis_state='ready' GROUP BY s.partition_name,s.source,t.scenario,t.expected_label
                   ORDER BY s.partition_name,s.source,t.scenario''').fetchall()
            groups = [{'partition': r['partition_name'], 'source': r['source'], 'scenario': r['scenario'], 'label': r['expected_label'],
                       'windows': r['windows'], 'eligible': r['eligible'], 'excluded': r['windows']-r['eligible']} for r in rows]
            real = {part: sum(r['eligible'] for r in groups if r['source'] == 'real' and r['partition'] == part) for part in ('train', 'test')}
            total = db.execute('SELECT COUNT(*) FROM collection_sessions').fetchone()[0]
            return {'groups': groups, 'real': real, 'minimumTestObservations': 100, 'minimumMet': real['test'] >= 100,
                    'targets': {'train': 200, 'test': 100}, 'sessionCount': total}
