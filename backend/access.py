"""Autorizacion de maqueta. Nunca usa una prediccion como permiso."""
import csv
import io
import json
import logging
import math
import threading
import time
import uuid

from .credentials import PinVerifier, valid_pin
from .errors import BackendError, DeviceUnavailable, NotFound, ValidationError
from .protocol import ROLES, default_config
from .storage import utc_now

logger = logging.getLogger(__name__)


class AccessFailure(BackendError):
    def __init__(self, message, status, attempt=None, retry_after=0):
        super().__init__(message)
        self.status_code, self.attempt, self.retry_after = status, attempt, retry_after


class Access:
    def __init__(self, service):
        self.service, self.store = service, service.store
        self.lock = service.experiments.lock
        self.pin = PinVerifier(service.settings.pin_file)
        self.active = False
        self.phase, self.reason = 'idle', 'Activa el modo con ambas capturas en curso.'
        self.run_id, self.started_at, self.captures = None, None, {}
        self.stopping = threading.Event()
        self.worker = threading.Thread(target=self._monitor, name='access-monitor', daemon=True)
        self.presence = {}

    def start_workers(self):
        from .monitoring import Monitoring
        self.monitoring = Monitoring(self.service, self)
        self.worker.start()
        self.monitoring.worker.start()

    def core_issue(self, states=None):
        if not self.store.health()['ok']:
            return 'Almacenamiento no disponible.'
        for row in states or self.service.snapshots():
            if not row['connected'] or not row['configured'] or row['phase'] != 'capturing':
                return 'Ambas placas deben estar conectadas, configuradas y capturando.'
            sample = row['latestSample']
            if row['config']['enabled'] != default_config(row['origin'])['enabled']:
                return 'Los cinco sensores deben permanecer habilitados.'
            if row['stale'] or not sample or sample.get('captureId') != row['captureId']:
                return 'Faltan datos recientes de las placas.'
            if sample.get('enabled') != row['config']['enabled']:
                return 'La mascara de sensores no coincide con la configuracion.'
            required = ('lux', 'sound') if row['origin'] == 'UNO' else ('pir', 'radar')
            if any(sample.get(field) is None for field in required):
                return 'Hay lecturas requeridas no disponibles. Distancia sin eco puede ser NA.'
            if self.active and self.captures.get(row['origin']) != row['captureId']:
                return 'Cambio de captura; vuelve a activar el modo.'
        return ''

    def blocked(self):
        with self.store.access() as db:
            value = db.execute('SELECT blocked_until FROM access_policy WHERE singleton=1').fetchone()[0]
        return value, max(0, math.ceil(value - time.time()))

    def status(self):
        until, remaining = self.blocked()
        issue = self.core_issue()
        return {'active': self.active, 'phase': self.phase, 'reason': self.reason,
                'pinConfigured': bool(self.pin.record), 'pinError': self.pin.error,
                'ready': self.active and not issue and not remaining and bool(self.pin.record),
                'canEnable': not self.active and not issue and bool(self.pin.record), 'issue': issue,
                'blockedUntil': until if remaining else None, 'retryAfter': remaining,
                'runId': self.run_id, 'startedAt': self.started_at,
                'acquisitionMode': 'simulated' if self.service.experiments.simulated else 'serial',
                'lastSignal': self.service.board('NANO').snapshot()['lastSignal']}

    def enable(self):
        if not self.lock.acquire(timeout=0.1):
            raise BackendError('Hay otra operacion en curso.')
        try:
            if self.active:
                return self.status()
            manager = self.service.experiments
            if manager.active_id or manager.individual_controls or manager.closing:
                raise BackendError('Termina el ensayo o control individual antes de activar acceso.')
            if not self.pin.record:
                raise DeviceUnavailable(self.pin.error)
            issue = self.core_issue()
            if issue:
                raise DeviceUnavailable(issue)
            state = self.service.board('NANO').submit('signal_caps')
            if not state['signalSupported']:
                raise DeviceUnavailable('El Nano requiere firmware con capacidad de senalizacion.')
            issue = self.core_issue()
            if issue:
                raise DeviceUnavailable(issue)
            self.run_id, self.started_at = str(uuid.uuid4()), utc_now()
            self.captures = {row['origin']: row['captureId'] for row in self.service.snapshots()}
            self.presence = {}
            self.store.incident('SYSTEM', 'ACCESS_MODE', f'Activado {self.run_id}')
            self.phase, self.reason, self.active = 'active', '', True
            return self.status()
        finally:
            self.lock.release()

    def _signal(self, result, request_id=None):
        return self.service.board('NANO').submit('signal', {'requestId': request_id or str(uuid.uuid4()), 'result': result})

    def _deactivate(self, reason, fault=False):
        was_active = self.active
        self.active = False
        self.phase, self.reason = ('suspended' if fault else 'idle'), reason
        nano = self.service.board('NANO').snapshot()
        if was_active and nano['connected'] and nano['signalSupported'] and not nano['busy']:
            try:
                self._signal('FAULT' if fault and nano['phase'] == 'capturing' else 'OFF')
            except Exception:
                logger.warning('No se confirmo el apagado/senal de falla del LED; el firmware limita su duracion.')
        if was_active:
            self.store.incident('SYSTEM', 'ACCESS_FAULT' if fault else 'ACCESS_MODE', reason)

    def disable(self, reason='Modo desactivado por el operador.'):
        with self.lock:
            self._deactivate(reason)
            return self.status()

    @staticmethod
    def public_attempt(row):
        return {'id': row['request_id'], 'cursor': row['ordinal'], 'at': row['at'], 'decision': row['decision'],
                'authorization': row['authorization'], 'signal': row['signal'], 'reason': row['reason'],
                'observations': json.loads(row['snapshot_json'])}

    def get_attempt(self, request_id):
        with self.store.access() as db:
            row = db.execute('SELECT * FROM access_attempts WHERE request_id=?', (request_id,)).fetchone()
        if not row:
            raise NotFound('Intento no encontrado; no se repetira la solicitud.')
        return self.public_attempt(row)

    def attempts(self, after_id=0, limit=20):
        with self.store.access() as db:
            rows = db.execute('SELECT * FROM access_attempts WHERE (?=0 OR ordinal<?) ORDER BY ordinal DESC LIMIT ?',
                              (after_id, after_id, limit)).fetchall()
        return {'items': [self.public_attempt(row) for row in rows], 'nextCursor': rows[-1]['ordinal'] if rows else after_id}

    def _finish(self, request_id, decision, signal, reason):
        with self.store.access(True) as db:
            db.execute('UPDATE access_attempts SET decision=?,signal=?,reason=? WHERE request_id=?',
                       (decision, signal, reason, request_id))
        return self.get_attempt(request_id)

    def _respond(self, attempt):
        status = {'allowed': 200, 'denied': 403, 'blocked': 429, 'pending': 409, 'unconfirmed': 504, 'unavailable': 503}[attempt['decision']]
        if status != 200:
            raise AccessFailure(attempt['reason'], status, attempt, self.blocked()[1] if status == 429 else 0)
        return attempt

    def attempt(self, request_id, pin):
        if not valid_pin(pin):
            raise ValidationError('El PIN debe contener seis digitos.')
        request_id = str(uuid.UUID(request_id))
        if not self.lock.acquire(timeout=0.1):
            raise BackendError('Hay otra operacion en curso; consulta el estado antes de enviar otro intento.')
        try:
            with self.store.access() as db:
                old = db.execute('SELECT * FROM access_attempts WHERE request_id=?', (request_id,)).fetchone()
            if old:
                return self._respond(self.public_attempt(old))
            states = self.service.snapshots()
            snapshots = {row['origin']: {'captureId': row['captureId'], 'config': row['config'], 'sample': row['latestSample']}
                         for row in states}
            with self.store.access(True) as db:
                db.execute("INSERT INTO access_attempts(request_id,at,decision,authorization,signal,reason,snapshot_json) VALUES(?,?,'pending','none','pending','En proceso',?)",
                           (request_id, utc_now(), json.dumps(snapshots)))
            if not self.active or not self.pin.record:
                return self._respond(self._finish(request_id, 'unavailable', 'not_sent', 'Activa el modo de acceso antes de solicitarlo.'))
            issue = self.core_issue(states)
            if issue:
                self._deactivate(issue, fault=True)
                return self._respond(self._finish(request_id, 'unavailable', 'not_sent', issue))
            if self.blocked()[1]:
                return self._respond(self._finish(request_id, 'blocked', 'not_sent', 'Limite de intentos. Espera antes de volver a probar.'))
            accepted = self.pin.verify(pin)
            now = time.time()
            with self.store.access(True) as db:
                policy = db.execute('SELECT * FROM access_policy WHERE singleton=1').fetchone()
                failures = 0 if accepted else (policy['failures'] if 0 <= now - policy['window_started'] < 60 else 0) + 1
                window = 0 if accepted else (policy['window_started'] if failures > 1 else now)
                blocked = now + 60 if failures >= 5 else 0
                db.execute('UPDATE access_policy SET failures=?,window_started=?,blocked_until=? WHERE singleton=1', (failures, window, blocked))
                db.execute('UPDATE access_attempts SET authorization=? WHERE request_id=?', ('allow' if accepted else 'deny', request_id))
            # Comprobar otra vez despues del KDF, antes de enviar una senal de permiso.
            issue = self.core_issue()
            if issue:
                self._deactivate(issue, fault=True)
                return self._respond(self._finish(request_id, 'unavailable', 'not_sent', issue))
            try:
                self._signal('ALLOW' if accepted else 'DENY', request_id)
            except Exception:
                self.active, self.phase, self.reason = False, 'suspended', 'Senal sin confirmar; vuelve a comprobar las placas.'
                return self._respond(self._finish(request_id, 'unconfirmed', 'unconfirmed', self.reason))
            return self._respond(self._finish(request_id, 'allowed' if accepted else 'denied', 'confirmed',
                                               'PIN permitido; senal aceptada por Nano.' if accepted else 'PIN rechazado.'))
        finally:
            self.lock.release()

    def export(self):
        with self.store.access() as db:
            cutoff = db.execute('SELECT COALESCE(MAX(ordinal),0) FROM access_attempts').fetchone()[0]
        def chunks():
            buffer = io.StringIO(newline='')
            writer = csv.writer(buffer)
            writer.writerow(['request_id', 'fecha_hora', 'decision', 'autorizacion', 'senal', 'motivo', 'observaciones'])
            yield '\ufeff' + buffer.getvalue()
            cursor = 0
            while True:
                with self.store.access() as db:
                    rows = db.execute('SELECT * FROM access_attempts WHERE ordinal>? AND ordinal<=? ORDER BY ordinal LIMIT 500', (cursor, cutoff)).fetchall()
                if not rows:
                    return
                for row in rows:
                    buffer.seek(0); buffer.truncate(0)
                    writer.writerow([row[key] for key in ('request_id', 'at', 'decision', 'authorization', 'signal', 'reason', 'snapshot_json')])
                    yield buffer.getvalue()
                cursor = rows[-1]['ordinal']
        return chunks()

    def _monitor(self):
        while not self.stopping.wait(0.1):
            if not self.active or not self.lock.acquire(blocking=False):
                continue
            try:
                states = self.service.snapshots()
                issue = self.core_issue(states)
                if issue:
                    self._deactivate(issue, fault=True)
                    continue
                nano = next(row for row in states if row['origin'] == 'NANO')
                sample = nano['latestSample']
                for field in ('pir', 'radar'):
                    if sample[field] == 1 and self.presence.get(field) != 1:
                        self.store.incident('NANO', 'ACCESS_SENSOR', f'{field}=1; muestra {sample["id"]}', nano['captureId'])
                    self.presence[field] = sample[field]
            except Exception:
                self.active, self.phase, self.reason = False, 'suspended', 'Fallo de supervision; revisa almacenamiento y placas.'
                nano = self.service.board('NANO').snapshot()
                if nano['connected'] and not nano['busy']:
                    try:
                        self._signal('OFF')
                    except Exception:
                        pass
                logger.error('Modo de acceso suspendido por fallo de supervision.')
            finally:
                self.lock.release()

    def close(self):
        self.stopping.set()
        with self.lock:
            try:
                self._deactivate('Cierre del servicio.')
            except Exception:
                self.active = False
                logger.error('Cierre de acceso sin almacenamiento disponible; no se repetiran solicitudes.')
        for worker in (self.worker, self.monitoring.worker):
            worker.join(timeout=10)
            if worker.is_alive():
                raise DeviceUnavailable('Un trabajador de acceso sigue activo; SQLite permanece abierto.')
