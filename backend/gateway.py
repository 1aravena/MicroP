"""Un UART fisico con canales logicos UNO/NANO y peticiones correlacionadas.

Solo este trabajador escribe al maestro. Incluye los POLL del esclavo: nunca
solapa trafico host con la respuesta SoftwareSerial del Nano.
"""
import queue
import threading
import time

from .errors import BackendError, DeviceUnavailable
from .protocol import ROLES
from .transport import LineFramer, SerialFactory, canonical_port
from .storage import utc_now


class SharedRegistry:
    # La exclusividad fisica y de cada rol la verifica GatewayFactory.open_for.
    def claim(self, port, origin):
        pass

    def release(self, port, origin):
        pass


class Channel:
    def __init__(self, hub, origin):
        self.hub, self.origin = hub, origin
        self.closed = False
        self.incoming = queue.Queue(maxsize=256)
        self.pending = bytearray()
        self.received_at = None

    def fail(self, error):
        while True:
            try:
                self.incoming.get_nowait()
            except queue.Empty:
                break
        self.pending.clear()
        self.incoming.put_nowait(error)

    def deliver(self, line):
        if not self.closed:
            try:
                self.incoming.put_nowait((line, utc_now()))
            except queue.Full:
                self.fail(DeviceUnavailable('Cola del UART saturada; reconecta y revisa la adquisicion.'))

    def read(self, size):
        if self.closed:
            raise DeviceUnavailable('Canal del maestro cerrado.')
        if not self.pending:
            try:
                packet = self.incoming.get(timeout=self.hub.settings.read_timeout)
            except queue.Empty:
                return b''
            if isinstance(packet, Exception):
                raise packet
            line, self.received_at = packet
            self.pending.extend((line + '\n').encode('ascii'))
        data = bytes(self.pending[:size])
        del self.pending[:size]
        return data

    def write(self, data):
        if self.closed:
            raise DeviceUnavailable('Canal del maestro cerrado.')
        command = data.decode('ascii').rstrip('\n')
        if not command or '\n' in command or '\r' in command or len(command) > 95:
            raise BackendError('Comando de pasarela invalido.')
        self.hub.enqueue(self, command)
        return len(data)

    def close(self):
        if not self.closed:
            self.hub.release(self)
            self.closed = True


class GatewayFactory:
    def __init__(self, settings, physical=None):
        self.settings = settings
        self.physical = physical or SerialFactory()
        self.is_simulated = getattr(self.physical, 'is_simulated', not isinstance(self.physical, SerialFactory))
        self.lock = threading.RLock()
        self.jobs = queue.Queue(maxsize=32)
        self.channels = {}
        self.connection = None
        self.thread = None
        self.stopping = threading.Event()
        self.framer = LineFramer(256)
        self.identifier = 0
        self.last_error = ''
        self.control = threading.Lock()

    def ports(self):
        items = self.physical.ports()
        # /dev/serial0 no suele aparecer en list_ports. Es una ruta fijada por
        # configuracion local, nunca una ruta arbitraria enviada por HTTP.
        import os
        if os.name == 'posix' and os.path.exists(self.settings.serial_port) and not any(
                canonical_port(item['device']) == canonical_port(self.settings.serial_port) for item in items):
            items.append({'device': self.settings.serial_port, 'description': 'UART GPIO del Uno maestro',
                          'serialNumber': None, 'location': 'GPIO14/15'})
        return [item for item in items if canonical_port(item['device']) == canonical_port(self.settings.serial_port)]

    def status(self):
        with self.lock:
            return {'mode': 'gateway', 'port': self.settings.serial_port, 'baudrate': 115200,
                    'nanoBaudrate': 9600, 'connected': self.connection is not None and not self.stopping.is_set(),
                    'busy': self.control.locked(), 'lastError': self.last_error,
                    'roles': sorted(self.channels)}

    def open_for(self, origin, port, settings):
        with self.lock:
            if canonical_port(port) != canonical_port(self.settings.serial_port):
                raise DeviceUnavailable('Selecciona el UART del maestro definido en serial_port.')
            if origin in self.channels:
                raise BackendError('Este rol ya esta conectado al maestro.')
            if self.connection is None:
                if self.channels:
                    raise DeviceUnavailable('Espera la desconexion de ambos canales antes de reconectar el maestro.')
                self._open()
            channel = Channel(self, origin)
            self.channels[origin] = channel
            return channel

    def _open(self):
        self.stopping.clear()
        self.framer = LineFramer(256)
        self.jobs = queue.Queue(maxsize=32)
        self.last_error = ''
        self.connection = self.physical.open(self.settings.serial_port, self.settings)
        try:
            self.stopping.wait(self.settings.reset_delay)
            self._write(b'GATEWAY_INFO\n')
            deadline = time.monotonic() + self.settings.command_timeout
            while time.monotonic() < deadline:
                packet = self._line()
                if packet and packet[0] == '@OK,GATEWAY,1,UNO,NANO,9600':
                    break
            else:
                raise DeviceUnavailable('Uno sin pasarela confirmada. Carga el firmware maestro actualizado y revisa UART/baudrate.')
        except Exception:
            self.connection.close()
            self.connection = None
            raise
        self.thread = threading.Thread(target=self._run, name='uart-master', daemon=True)
        self.thread.start()

    def _write(self, data):
        if self.connection is None or self.connection.write(data) != len(data):
            raise DeviceUnavailable('Escritura incompleta en el UART del maestro.')

    def _line(self):
        if not self.framer.ready:
            data = self.connection.read(256)
            if data:
                self.framer.feed(data)
        return self.framer.ready.popleft() if self.framer.ready else None

    def enqueue(self, channel, command, done=None):
        if self.connection is None or self.stopping.is_set():
            raise DeviceUnavailable('Maestro desconectado. Reconecta el enlace UART.')
        try:
            self.jobs.put_nowait((channel, command, done))
        except queue.Full:
            raise BackendError('El maestro tiene demasiados comandos pendientes.') from None

    def _dispatch(self, packet, expected=None, internal=False):
        line, error = packet
        if error:
            raise DeviceUnavailable(error)
        if line.startswith('@READY'):
            raise DeviceUnavailable('El Uno maestro se reinicio. Reconecta y aplica configuracion nuevamente.')
        if not line.startswith('@FROM,'):
            return False
        fields = line.split(',', 3)
        if len(fields) != 4 or fields[1] not in ROLES or not fields[2].isdigit():
            raise DeviceUnavailable('Trama de pasarela invalida.')
        _, origin, identifier, payload = fields
        identifier = int(identifier)
        channel = self.channels.get(origin)
        matched = expected == (origin, identifier)
        # Un ACK de una peticion vencida nunca llega a otra operacion.
        if identifier == 0 or (matched and not internal):
            if channel:
                channel.deliver(payload)
        terminal = payload.startswith('@OK,') or (payload.startswith('@ERR,') and not payload.startswith('@ERR,READ,'))
        if matched and terminal and internal and payload.startswith('@ERR,'):
            if origin == 'NANO' and channel:
                channel.fail(DeviceUnavailable('El Nano esclavo no responde: ' + payload))
            elif origin == 'UNO':
                raise DeviceUnavailable('El maestro no confirma su estado.')
        return matched and terminal

    def _execute(self, channel, command, internal=False):
        self.identifier = self.identifier % 0xFFFFFFFE + 1
        identifier = self.identifier
        self._write(f'@TO,{channel.origin},{identifier},{command}\n'.encode('ascii'))
        deadline = time.monotonic() + self.settings.command_timeout
        while not self.stopping.is_set() and time.monotonic() < deadline:
            packet = self._line()
            if packet and self._dispatch(packet, (channel.origin, identifier), internal):
                return
        if not self.stopping.is_set():
            # Sin respuesta del maestro no se puede asegurar ningun canal.
            raise DeviceUnavailable('Timeout del Uno maestro. Consulta estado y reconecta; el comando no se repite.')

    def _run(self):
        next_poll, next_heartbeat = time.monotonic(), time.monotonic() + 2
        try:
            while not self.stopping.is_set():
                try:
                    channel, command, done = self.jobs.get_nowait()
                except queue.Empty:
                    now = time.monotonic()
                    channel = self.channels.get('NANO')
                    if channel and now >= next_poll:
                        self._execute(channel, 'POLL', internal=True)
                        next_poll = time.monotonic() + 0.1
                    elif self.channels and now >= next_heartbeat:
                        channel = self.channels.get('UNO')
                        if channel:
                            self._execute(channel, 'INFO', internal=True)
                        next_heartbeat = time.monotonic() + 2
                    else:
                        packet = self._line()
                        if packet:
                            self._dispatch(packet)
                    continue
                try:
                    if not channel.closed:
                        self._execute(channel, command)
                finally:
                    if done:
                        done.set()
        except Exception as error:
            self.last_error = str(error)
            self.stopping.set()
            for channel in list(self.channels.values()):
                channel.fail(DeviceUnavailable(self.last_error))
        finally:
            if self.connection:
                self.connection.close()
            self.connection = None

    def release(self, channel):
        done = threading.Event()
        try:
            self.enqueue(channel, 'STOP', done)
            done.wait(self.settings.command_timeout + 0.5)
        except BackendError:
            pass
        with self.lock:
            if self.channels.get(channel.origin) is channel:
                del self.channels[channel.origin]

    def close(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=self.settings.command_timeout + self.settings.read_timeout + 2)
            if self.thread.is_alive():
                raise DeviceUnavailable('El trabajador UART no termino.')
        if self.connection:
            self.connection.close()
            self.connection = None
