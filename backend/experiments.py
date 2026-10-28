"""Coordinacion de ensayos sin trasladar acceso serial al hilo HTTP."""
from contextlib import contextmanager
import logging
import threading

from .dataset import AnalysisCancelled, FEATURE_VERSION, POLICY, analyze_trial
from .errors import BackendError, DeviceUnavailable, StorageError, ValidationError
from .experiment_store import ExperimentStore
from .protocol import ROLES, default_config
from .storage import utc_now
from .transport import SerialFactory

logger = logging.getLogger(__name__)
SCENARIOS = (
    {'id': 'zona_vacia', 'name': 'Zona vacía', 'label': 'normal', 'procedure': 'Mantener libre el área vigilada durante la ventana.'},
    {'id': 'paso_breve', 'name': 'Paso breve', 'label': 'normal', 'procedure': 'Realizar un paso frente al acceso y retirarse.'},
    {'id': 'acercamientos_repetidos', 'name': 'Acercamientos repetidos', 'label': 'anomalo', 'procedure': 'Realizar al menos dos ciclos de acercamiento y retirada en diez segundos.'},
    {'id': 'permanencia_proxima', 'name': 'Permanencia próxima', 'label': 'anomalo', 'procedure': 'Permanecer en la posición próxima durante la mayor parte de la ventana.'},
)
SCENARIO_BY_ID = {item['id']: item for item in SCENARIOS}


class Experiments:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.repository = ExperimentStore(self.store)
        self.lock = threading.RLock()
        self.active_id = None
        self.individual_controls = 0
        self.closing = False
        self.stopping = threading.Event()
        self.simulated = getattr(service.factory, 'is_simulated', not isinstance(service.factory, SerialFactory))
        self.monitor = threading.Thread(target=self._monitor, name='trial-monitor', daemon=True)
        self.processor = threading.Thread(target=self._process, name='dataset-analysis', daemon=True)
        self.monitor.start()
        self.processor.start()

    def catalog(self):
        return {'items': SCENARIOS, 'policy': POLICY, 'acquisitionMode': 'simulated' if self.simulated else 'serial',
                'featureVersion': FEATURE_VERSION}

    @contextmanager
    def individual(self):
        if not self.lock.acquire(blocking=False):
            raise BackendError('Hay una operacion de ensayo en curso. Consulta su estado antes de controlar una placa.')
        try:
            if self.closing:
                raise DeviceUnavailable('Servicio cerrandose.')
            if self.active_id:
                raise BackendError('Las placas estan reservadas por un ensayo. Usa Detener ensayo.')
            self.individual_controls += 1
        finally:
            self.lock.release()
        try:
            yield
        finally:
            with self.lock:
                self.individual_controls -= 1

    def create_session(self, values):
        values = dict(values)
        for key in ('name', 'responsible', 'conditions'):
            values[key] = values[key].strip()
            if not values[key]:
                raise ValidationError(f'El campo {key} no puede quedar vacio.')
        if values['source'] == 'real' and self.simulated:
            raise ValidationError('El transporte de pruebas es simulado; no puede declarar datos reales.')
        with self.lock:
            return self.repository.create_session(values)

    def create_trial(self, session_id, scenario, notes=''):
        if scenario not in SCENARIO_BY_ID:
            raise ValidationError('Escenario desconocido.')
        with self.lock:
            return self.repository.create_trial(session_id, SCENARIO_BY_ID[scenario], notes)

    def active(self):
        with self.store.access() as db:
            row = db.execute("SELECT trial_id FROM trials WHERE status IN ('starting','running','stopping') ORDER BY ordinal LIMIT 1").fetchone()
        return self.repository.trial(row['trial_id']) if row else None

    def start(self, trial_id):
        with self.lock:
            if self.closing:
                raise DeviceUnavailable('Servicio cerrandose.')
            if not self.store.health()['ok']:
                raise StorageError('No se puede iniciar un ensayo sin almacenamiento disponible.')
            trial = self.repository.trial(trial_id)
            if self.active_id == trial_id and trial['status'] == 'running':
                return trial
            if self.active_id or self.individual_controls:
                raise BackendError('Hay un ensayo o control individual en curso.')
            if getattr(getattr(self.service, 'access', None), 'active', False):
                raise BackendError('Desactiva el modo de acceso antes de iniciar un ensayo.')
            if trial['status'] != 'prepared' or self.repository.session(trial['sessionId'])['status'] != 'open':
                raise BackendError('Solo puede iniciarse un ensayo preparado de una sesion abierta.')
            snapshots = self.service.snapshots()
            for board in snapshots:
                if not board['connected'] or not board['configured'] or board['busy'] or board['phase'] != 'configured':
                    raise BackendError('Ambas placas deben estar conectadas, configuradas y detenidas.')
                if board['config']['enabled'] != default_config(board['origin'])['enabled']:
                    raise ValidationError('El ensayo requiere los cinco sensores habilitados en sus placas.')
            before = {row['origin']: row['captureId'] for row in snapshots}
            self.active_id = trial_id
            try:
                self.repository.update_trial(trial_id, status='starting', started_at=utc_now())
                for origin in ROLES:
                    state = self.service.board(origin).submit('start')
                    self.repository.link(trial_id, origin, state['captureId'])
                states = self.service.snapshots()
                if any(not row['connected'] or row['phase'] != 'capturing' for row in states):
                    raise DeviceUnavailable('Una placa perdio el enlace durante el inicio.')
                linked = self.repository.trial(trial_id)
                common_start = max(capture['startedAt'] for capture in linked['captureDetails'].values())
                self.repository.update_trial(trial_id, status='running', started_at=common_start)
                self.store.incident('SYSTEM', 'TRIAL_START', f'Ensayo {trial_id}')
                return self.repository.trial(trial_id)
            except Exception:
                # Conservar incluso una captura cuyo resultado llego antes de un error de control.
                try:
                    linked = self.repository.trial(trial_id)['captures']
                    for origin in ROLES:
                        state = self.service.board(origin).snapshot()
                        if origin not in linked and state['captureId'] and state['captureId'] != before[origin]:
                            self.repository.link(trial_id, origin, state['captureId'])
                except Exception:
                    logger.exception('No se pudo asociar la captura parcial.')
                finally:
                    try:
                        self._interrupt_locked('partial_start')
                    except Exception:
                        logger.exception('Compensacion ejecutada sin poder guardar el estado final.')
                raise

    def _stop_boards(self):
        errors = []
        for origin in ROLES:
            board = self.service.board(origin)
            if board.snapshot()['connected']:
                try:
                    board.submit('stop')
                except Exception as error:
                    errors.append(str(error))
        return errors

    def _interrupt_locked(self, reason):
        trial_id = self.active_id
        if trial_id is None:
            return
        try:
            errors = self._stop_boards()
            self.repository.update_trial(trial_id, status='interrupted', ended_at=utc_now(), end_reason=reason,
                                         reviewed=0, reviewed_at=utc_now(), analysis_state='pending',
                                         review_notes='Ensayo excluido por interrupcion.' + (' ' + '; '.join(errors) if errors else ''))
            self.store.incident('SYSTEM', 'TRIAL_INTERRUPTED', f'{trial_id}: {reason}')
        finally:
            self.active_id = None

    def stop(self, trial_id):
        with self.lock:
            trial = self.repository.trial(trial_id)
            if trial['status'] in ('completed', 'interrupted'):
                return trial
            if trial['status'] == 'prepared':
                self.repository.update_trial(trial_id, status='interrupted', ended_at=utc_now(), end_reason='cancelled_before_start',
                                             reviewed=0, reviewed_at=utc_now(), analysis_state='pending')
                return self.repository.trial(trial_id)
            if self.active_id != trial_id:
                raise BackendError('El ensayo no es el activo.')
            self.repository.update_trial(trial_id, status='stopping')
            errors = self._stop_boards()
            captures = self.repository.trial(trial_id)['captureDetails']
            if errors or len(captures) != 2 or any(item['status'] != 'stopped' for item in captures.values()):
                self._interrupt_locked('stop_unconfirmed')
            else:
                end = min(item['endedAt'] for item in captures.values())
                self.repository.update_trial(trial_id, status='completed', ended_at=end, end_reason='manual_stop')
                self.active_id = None
                self.store.incident('SYSTEM', 'TRIAL_STOP', f'Ensayo {trial_id}; requiere confirmacion humana.')
            return self.repository.trial(trial_id)

    def review(self, trial_id, confirmed, notes=''):
        with self.lock:
            trial = self.repository.trial(trial_id)
            if trial['status'] not in ('completed', 'interrupted'):
                raise BackendError('Deten el ensayo antes de confirmar el escenario.')
            if trial['status'] == 'interrupted' and confirmed:
                raise BackendError('Un ensayo interrumpido no puede confirmarse para ML; repite el ensayo.')
            if self.repository.session(trial['sessionId'])['status'] == 'closed':
                raise BackendError('La sesion cerrada no admite cambios.')
            if trial['reviewed'] is not None:
                if trial['reviewed'] != confirmed:
                    raise BackendError('La revision ya esta fijada. Conserva el registro y realiza otro ensayo.')
                if trial['analysisState'] != 'error':
                    return trial
            self.repository.update_trial(trial_id, reviewed=int(confirmed), reviewed_at=utc_now(), review_notes=notes,
                                         analysis_state='pending', analysis_error=None)
            return self.repository.trial(trial_id)

    def close_session(self, session_id):
        with self.lock:
            return self.repository.close_session(session_id)

    def _monitor(self):
        while not self.stopping.wait(0.1):
            if not self.active_id or not self.lock.acquire(blocking=False):
                continue
            try:
                trial = self.repository.trial(self.active_id)
                if trial['status'] == 'running':
                    states = self.service.snapshots()
                    failed = any(not row['connected'] or row['phase'] != 'capturing' or row['stale']
                                 or row['captureId'] != trial['captures'].get(row['origin']) for row in states)
                    if failed:
                        self._interrupt_locked('board_failure')
            except Exception:
                logger.exception('Fallo al supervisar el ensayo; se intenta detener las placas.')
                try:
                    self._interrupt_locked('supervision_failure')
                except Exception:
                    logger.exception('No se pudo guardar la interrupcion; se recuperara al reiniciar.')
            finally:
                self.lock.release()

    def _process(self):
        while not self.stopping.wait(0.1):
            trial_id = None
            try:
                with self.lock:
                    trial_id = self.repository.pending()
                    if trial_id:
                        self.repository.update_trial(trial_id, analysis_state='processing', analysis_error=None)
                if trial_id:
                    analyze_trial(self.store, self.repository, trial_id, cancelled=self.stopping.is_set)
            except AnalysisCancelled:
                self.repository.update_trial(trial_id, analysis_state='pending')
            except Exception as error:
                logger.exception('No se pudo analizar el ensayo %s', trial_id)
                if trial_id:
                    try:
                        self.repository.update_trial(trial_id, analysis_state='error', analysis_error=str(error))
                    except Exception:
                        logger.exception('No se pudo registrar el error de analisis.')
                self.stopping.wait(0.5)

    def close(self):
        with self.lock:
            self.closing = True
            if self.active_id:
                try:
                    self._interrupt_locked('service_shutdown')
                except Exception:
                    logger.exception('Cierre de ensayo sin almacenamiento disponible.')
        self.stopping.set()
        for worker in (self.monitor, self.processor):
            worker.join(timeout=10)
            if worker.is_alive():
                raise DeviceUnavailable('Un trabajador de ensayos sigue activo; no se cerrara SQLite.')
