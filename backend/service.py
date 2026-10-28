"""Un actor por placa: solo su trabajador accede al puerto y procesa los ACK."""
from concurrent.futures import Future, TimeoutError as FutureTimeout
from copy import deepcopy
import logging
import queue
import threading
import time
import platform
import socket
from pathlib import Path
from uuid import UUID

from .config import Settings
from .errors import BackendError, CapabilityUnavailable, CommandTimeout, DeviceUnavailable, StorageError, ValidationError
from .protocol import (FIELDS, ROLES, SENSOR_COMMANDS, SENSOR_KEYS, check_origin, default_config,
                       matches_ack, parse_identity, parse_sample, serialize_config)
from .storage import Store, utc_now
from .transport import LineFramer, PortRegistry, SerialFactory

logger = logging.getLogger(__name__)


class Board:
    def __init__(self, origin, store, factory, registry, settings):
        self.origin, self.store, self.factory, self.registry, self.settings = origin, store, factory, registry, settings
        self.connection = None
        self.port = None
        self.config = default_config(origin)
        self.active_capture = None
        self.last_sequence = self.last_device_time = 0
        self.since = None
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.operation = threading.Lock()
        self.tasks = queue.Queue(maxsize=1)
        self.framer = LineFramer()
        self.packet_received_at = None
        self.state = {"origin": origin, "connected": False, "configured": False, "busy": False,
                      "phase": "disconnected", "port": None, "config": deepcopy(self.config),
                      "captureId": None, "sampleCount": 0, "latestSample": None,
                      "lastReceivedAt": None, "lastError": None, "signalSupported": False, "lastSignal": None}
        self.thread = threading.Thread(target=self._run, name=f"serial-{origin}", daemon=True)

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def snapshot(self):
        with self.lock:
            result = deepcopy(self.state)
            age = None if self.since is None else max(0, round((time.monotonic() - self.since) * 1000))
            result.update(ageMs=age, stale=result["phase"] == "capturing" and age is not None and age > self.settings.stale_after * 1000)
            return result

    def submit(self, action, payload=None):
        if self.stopping.is_set() or not self.thread.is_alive():
            raise DeviceUnavailable("El trabajador de la placa no esta disponible.")
        if not self.operation.acquire(blocking=False):
            raise BackendError("Hay otro comando en curso en esta placa.")
        future = Future()
        self.update(busy=True)
        try:
            self.tasks.put_nowait((action, deepcopy(payload), future))
        except Exception:
            self.update(busy=False)
            self.operation.release()
            raise
        try:
            return future.result(timeout=3 * self.settings.command_timeout + self.settings.reset_delay + 3)
        except FutureTimeout as error:
            raise CommandTimeout("La operacion no termino a tiempo; consulta el estado antes de repetirla.") from error

    def incident(self, kind, description):
        self.store.incident(self.origin, kind, description, self.active_capture)

    def _run(self):
        try:
            while not self.stopping.is_set():
                failure = None
                try:
                    action, payload, future = self.tasks.get_nowait()
                except queue.Empty:
                    if self.connection is None:
                        self.stopping.wait(0.02)
                    else:
                        try:
                            packet = self._next_line()
                            if packet:
                                self._receive(*packet)
                        except StorageError as error:
                            self._storage_fault(error)
                        except Exception as error:
                            self._lost(error)
                    continue
                try:
                    handlers = {"connect": self._connect, "disconnect": self._disconnect,
                                "config": self._configure, "start": self._start,
                                "stop": self._stop, "enable": self._enable,
                                "signal_caps": self._signal_caps, "signal": self._signal}
                    handlers[action](payload)
                except StorageError as error:
                    self._storage_fault(error)
                    failure = error
                except DeviceUnavailable as error:
                    self._lost(error)
                    failure = error
                except Exception as error:
                    try:
                        self.incident("CONTROL", str(error))
                    except StorageError as storage_error:
                        self._storage_fault(storage_error)
                    self.update(lastError=str(error))
                    failure = error if isinstance(error, BackendError) else DeviceUnavailable(str(error))
                finally:
                    self.update(busy=False)
                    self.operation.release()
                if failure is None:
                    future.set_result(self.snapshot())
                else:
                    future.set_exception(failure)
        finally:
            try:
                self._drop("service_shutdown", "stopped")
            except StorageError as error:
                logger.error("%s: %s", self.origin, error)
            while True:
                try:
                    _, _, future = self.tasks.get_nowait()
                except queue.Empty:
                    break
                future.set_exception(DeviceUnavailable("Servicio detenido."))
                self.update(busy=False)
                self.operation.release()

    def _next_line(self):
        if not self.framer.ready:
            try:
                data = self.connection.read(256)
            except Exception as error:
                raise DeviceUnavailable(f"Fallo al recibir por serial: {error}") from error
            if data:
                self.framer.feed(data)
                self.packet_received_at = getattr(self.connection, 'received_at', None)
        return self.framer.ready.popleft() if self.framer.ready else None

    def _command(self, command):
        if self.connection is None:
            raise DeviceUnavailable("Placa no conectada.")
        try:
            data = (command + "\n").encode("ascii")
            if self.connection.write(data) != len(data):
                raise OSError("Escritura incompleta")
        except Exception as error:
            raise DeviceUnavailable(f"Fallo al escribir por serial: {error}") from error
        deadline = time.monotonic() + self.settings.command_timeout
        while not self.stopping.is_set():
            if time.monotonic() >= deadline:
                raise CommandTimeout(f"La placa no respondio a {command.split(',')[0]}; vuelve a configurar.")
            packet = self._next_line()
            if not packet:
                continue
            line, error = packet
            if line is not None and matches_ack(command, line):
                return line
            self._receive(line, error, in_command=True)
        raise DeviceUnavailable("Servicio deteniendose.")

    def _require_connection(self):
        if self.connection is None or not self.state["connected"]:
            raise BackendError("Primero conecta la placa.")

    def _signal_caps(self, _):
        self._require_connection()
        if self.origin != 'NANO':
            raise ValidationError('La senalizacion pertenece al Nano.')
        self.update(signalSupported=False)
        try:
            self._command('SIGNAL_CAPS')
        except DeviceUnavailable:
            raise
        except BackendError:
            raise CapabilityUnavailable('Nano sin capacidad de senalizacion confirmada. Actualiza su firmware.') from None
        self.update(signalSupported=True, lastError=None)

    def _signal(self, payload):
        self._require_connection()
        if self.origin != 'NANO' or not self.state['signalSupported']:
            raise DeviceUnavailable('Nano sin capacidad de senalizacion confirmada.')
        request_id = str(UUID(payload['requestId']))
        result = payload['result']
        if result not in ('ALLOW', 'DENY', 'FAULT', 'OFF'):
            raise ValidationError('Resultado de senal invalido.')
        try:
            self._command(f'SIGNAL,{request_id},{result}')
        except Exception:
            if result != 'OFF':
                self._invalidate('signal_unconfirmed')
            raise
        self.update(lastSignal={'id': request_id, 'result': result}, lastError=None)

    def _connect(self, payload):
        if self.connection is not None:
            raise BackendError("La placa ya esta conectada.")
        port = payload["port"]
        self.registry.claim(port, self.origin)
        self.port = port
        self.framer = LineFramer()
        self.update(phase="connecting", port=port, lastError=None)
        try:
            if hasattr(self.factory, 'open_for'):
                self.connection = self.factory.open_for(self.origin, port, self.settings)
            else:
                self.connection = self.factory.open(port, self.settings)
                self.stopping.wait(self.settings.reset_delay)
            parse_identity(self._command("INFO"), self.origin)
            self._command("STOP")
            self.incident("CONNECTED", f"Protocolo 2 verificado en {port}; requiere CONFIG.")
            self.since = None
            self.update(connected=True, configured=False, phase="unconfigured", latestSample=None, lastReceivedAt=None)
        except Exception:
            self._close_port()
            self.update(connected=False, configured=False, phase="disconnected", port=None)
            raise

    def _configure(self, config):
        self._require_connection()
        if self.state["phase"] == "capturing":
            raise BackendError("Deten la captura antes de cambiar pines.")
        if config.get("origin") != self.origin:
            raise ValidationError("Configuracion de otra placa.")
        command = serialize_config(config)
        if self.settings.transport == 'gateway' and self.origin == 'UNO':
            active_pins = ([config['hcTrigger'], config['hcEcho']] if config['enabled']['hc'] else [])
            if config['enabled']['sound']:
                active_pins.append(config['soundPin'])
            if any(pin in (2, 3) for pin in active_pins):
                raise ValidationError('D2/D3 del Uno estan reservados para UART con el Nano esclavo.')
        self.update(configured=False, phase="unconfigured")
        try:
            parse_identity(self._command("INFO"), self.origin)
            self._command("STOP")
            self._command(command)
            self.incident("CONFIGURED", command)
        except Exception:
            self._invalidate("config_failed")
            raise
        self.config = deepcopy(config)
        self.update(configured=True, phase="configured", config=deepcopy(config), lastError=None)

    def _start(self, _):
        self._require_connection()
        if not self.state["configured"] or self.state["phase"] != "configured":
            raise BackendError("Aplica configuracion antes de iniciar una captura nueva.")
        self.update(phase="starting")
        try:
            self._command("START")
            capture_id = self.store.create_capture(self.origin, self.config)
        except Exception:
            self._invalidate("start_failed")
            raise
        self.active_capture = capture_id
        self.last_sequence = self.last_device_time = 0
        self.since = time.monotonic()
        self.update(phase="capturing", captureId=capture_id, sampleCount=0, latestSample=None,
                    lastReceivedAt=None, lastError=None)

    def _stop(self, _):
        self._require_connection()
        try:
            self._command("STOP")
        except Exception:
            self._invalidate("stop_unconfirmed")
            raise
        self._end_capture("stopped", "manual_stop")
        self.incident("STOP", "STOP confirmado.")
        self.update(phase="configured" if self.state["configured"] else "unconfigured", lastError=None)

    def _enable(self, payload):
        self._require_connection()
        if not self.state["configured"]:
            raise BackendError("Primero aplica configuracion.")
        sensor, enabled = payload["sensor"], payload["enabled"]
        if sensor not in SENSOR_COMMANDS or type(enabled) is not bool:
            raise ValidationError("Sensor o estado invalido.")
        next_config = deepcopy(self.config)
        next_config["enabled"][sensor] = enabled
        serialize_config(next_config)
        command = f"ENABLE,{SENSOR_COMMANDS[sensor]},{int(enabled)}"
        try:
            self._command(command)
            self.incident("ENABLE", command)
        except Exception:
            self._invalidate("enable_unconfirmed")
            raise
        self.config = next_config
        self.update(config=deepcopy(next_config), lastError=None)

    def _disconnect(self, _):
        if self.connection is None:
            return
        try:
            self._command("STOP")
        except Exception:
            self._drop("disconnect_unconfirmed", "interrupted")
            raise
        self._drop("manual_disconnect", "stopped")

    def _end_capture(self, status, reason):
        if self.active_capture:
            self.store.end_capture(self.active_capture, status, reason)
            self.active_capture = None

    def _best_effort_stop(self):
        if self.connection is not None:
            try:
                self.connection.write(b"STOP\n")
            except Exception:
                pass

    def _invalidate(self, reason):
        self._best_effort_stop()
        self.update(configured=False, phase="unconfigured")
        self._end_capture("interrupted", reason)

    def _close_port(self):
        try:
            if self.connection is not None:
                self.connection.close()
        except Exception:
            logger.exception("%s: cierre del puerto", self.origin)
        finally:
            self.connection = None
            self.registry.release(self.port, self.origin)
            self.port = None

    def _drop(self, reason, status="interrupted"):
        was_connected = self.connection is not None
        self._best_effort_stop()
        self.update(connected=False, configured=False, phase="disconnected", port=None, signalSupported=False)
        try:
            self._end_capture(status, reason)
            if was_connected:
                self.incident("DISCONNECTED", reason)
        finally:
            self._close_port()

    def _lost(self, error):
        self.update(lastError=str(error))
        try:
            self.incident("TRANSPORT", str(error))
            self._drop("link_lost")
        except StorageError as storage_error:
            self._storage_fault(storage_error)

    def _storage_fault(self, error):
        logger.error("%s: adquisicion interrumpida, %s", self.origin, error)
        self._best_effort_stop()
        self._close_port()
        self.active_capture = None  # La base recuperara la captura inconclusa al reiniciar.
        self.update(connected=False, configured=False, phase="storage_error", port=None, lastError=str(error))

    def _receive(self, line, error=None, in_command=False):
        if error:
            self.incident("FRAME", error)
            return
        if line.startswith("@READY"):
            if self.state["connected"]:
                self._invalidate("device_reset")
                self.since = None
                self.update(latestSample=None, lastReceivedAt=None)
                self.incident("RESET", "Reinicio; requiere configuracion explicita.")
                if in_command:
                    raise BackendError("La placa se reinicio durante el comando.")
            return
        if line.startswith("@ERR"):
            self.incident("DEVICE", line)
            if in_command and not line.startswith("@ERR,READ,"):
                raise BackendError(line)
            return
        if line.startswith("@") or self.state["phase"] != "capturing" or not self.active_capture:
            return
        received_at = self.packet_received_at or utc_now()
        try:
            sample = parse_sample(line, self.config)
            if sample["sequence"] <= self.last_sequence or sample["timeMs"] < self.last_device_time:
                raise ValidationError("Secuencia repetida, fuera de orden o reinicio sin identificar.")
        except ValidationError as invalid:
            self.incident("INVALID", f"{invalid} Mensaje: {line}")
            return
        if sample["sequence"] != self.last_sequence + 1:
            self.incident("GAP", f"Salto de secuencia: {self.last_sequence} -> {sample['sequence']}.")
        missing = [key for key, field in zip(SENSOR_KEYS, FIELDS) if self.config["enabled"][key] and sample[field] is None]
        if missing:
            self.incident("MISSING", "Lectura no disponible: " + ", ".join(missing))
        saved = self.store.add_sample(self.active_capture, sample, self.config["enabled"], received_at)
        self.last_sequence, self.last_device_time = sample["sequence"], sample["timeMs"]
        self.since = time.monotonic()
        self.update(latestSample=saved, sampleCount=self.state["sampleCount"] + 1, lastReceivedAt=received_at)

    def close(self):
        self.stopping.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=3 * self.settings.command_timeout + self.settings.reset_delay + 3)
            if self.thread.is_alive():
                raise DeviceUnavailable(f"El trabajador {self.origin} no termino; no se cerrara la base mientras escriba.")


class AcquisitionService:
    def __init__(self, settings=None, factory=None):
        self.settings = settings or Settings()
        self.factory = factory or SerialFactory()
        if self.settings.transport == 'gateway':
            from .gateway import GatewayFactory, SharedRegistry
            self.factory = GatewayFactory(self.settings, self.factory)
            registry = SharedRegistry()
        else:
            registry = PortRegistry()
        self.store = Store(self.settings.database)
        self.boards = {origin: Board(origin, self.store, self.factory, registry, self.settings) for origin in ROLES}
        self.closed = False
        for board in self.boards.values():
            board.thread.start()
        from .experiments import Experiments
        self.experiments = Experiments(self)
        from .access import Access
        self.access = Access(self)
        self.access.start_workers()

    def board(self, origin):
        check_origin(origin)
        return self.boards[origin]

    def snapshots(self):
        owner = getattr(getattr(self, 'experiments', None), 'active_id', None)
        reserved = bool(getattr(getattr(self, 'access', None), 'active', False))
        return [{**board.snapshot(), 'trialId': owner, 'accessReserved': reserved} for board in self.boards.values()]

    def connection_status(self):
        transport = self.factory.status() if self.settings.transport == 'gateway' else {'mode': 'usb', 'baudrate': 115200}
        return {'transport': transport, 'runtime': {'hostname': socket.gethostname(), 'platform': platform.system(),
                'database': str(Path(self.settings.database).resolve()) if self.settings.database != ':memory:' else ':memory:'}}

    def gateway_control(self, action, port=None):
        if self.settings.transport != 'gateway':
            raise ValidationError('El backend esta en modo USB independiente.')
        if not self.factory.control.acquire(blocking=False):
            raise BackendError('Hay una operacion del maestro en curso.')
        try:
            with self.experiments.individual():
                if self.access.active:
                    if action == 'connect':
                        raise BackendError('Desactiva acceso antes de reconectar el maestro.')
                    self.access.disable('Desconexion del maestro solicitada por el operador.')
                failures = []
                for origin in (ROLES if action == 'connect' else tuple(reversed(ROLES))):
                    board = self.board(origin)
                    if action == 'connect' and board.snapshot()['connected']:
                        continue
                    try:
                        board.submit(action, {'port': port or self.settings.serial_port} if action == 'connect' else None)
                    except BackendError as error:
                        failures.append(f'{origin}: {error}')
                        if action == 'connect' and origin == 'UNO':
                            break
                if action == 'disconnect' and not self.factory.channels:
                    self.factory.close()
                if failures:
                    raise DeviceUnavailable(' '.join(failures))
                return {'items': self.snapshots(), **self.connection_status()}
        finally:
            self.factory.control.release()

    def control(self, origin, action, payload=None):
        with self.experiments.individual():
            if self.access.active:
                if action not in ('stop', 'disconnect'):
                    raise BackendError('Desactiva el modo de acceso antes de cambiar configuracion o capturas.')
                self.access.disable('Detencion o desconexion solicitada por el operador.')
            return self.board(origin).submit(action, payload)

    def close(self):
        if not self.closed:
            self.access.close()
            self.experiments.close()
            for board in self.boards.values():
                board.close()
            if self.settings.transport == 'gateway':
                self.factory.close()
            self.store.close()
            self.closed = True
