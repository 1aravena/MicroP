import queue
import threading
import time

from backend.errors import DeviceUnavailable


class FakePort:
    def __init__(self, origin, version=2):
        self.origin, self.version = origin, version
        self.commands = []
        self.closed = True
        self.queue = queue.Queue()
        self.pending = bytearray()
        self.on_command = None
        self.timeout = 0.005

    def open(self, settings):
        self.closed = False
        self.timeout = settings.read_timeout
        self.queue = queue.Queue()
        self.pending.clear()
        return self

    def emit(self, text):
        self.queue.put(text.encode("utf-8") if isinstance(text, str) else text)

    def unplug(self):
        self.queue.put(OSError("USB retirado (simulado)"))

    def read(self, size):
        if self.closed:
            raise OSError("Puerto cerrado")
        if not self.pending:
            try:
                packet = self.queue.get(timeout=self.timeout)
            except queue.Empty:
                return b""
            if isinstance(packet, Exception):
                raise packet
            self.pending.extend(packet)
        result = bytes(self.pending[:size])
        del self.pending[:size]
        return result

    def write(self, data):
        if self.closed:
            raise OSError("Puerto cerrado")
        command = data.decode("ascii").rstrip("\n")
        self.commands.append(command)
        if self.on_command and self.on_command(command, self) is False:
            return len(data)
        kind, *args = command.split(",")
        if kind == "INFO":
            self.emit(f"@OK,INFO,{self.version},{self.origin}\n")
        elif kind == "ENABLE":
            self.emit(f"@OK,ENABLE,{','.join(args)}\n")
        else:
            self.emit(f"@OK,{kind}\n")
        return len(data)

    def close(self):
        self.closed = True


class FakeFactory:
    def __init__(self):
        self.devices = {"UNO_PORT": FakePort("UNO"), "NANO_PORT": FakePort("NANO")}
        self.opens = []
        self.lock = threading.Lock()

    def ports(self):
        return [{"device": name, "description": "PERIFERICO SIMULADO DE PRUEBA", "serialNumber": None, "location": None}
                for name in self.devices]

    def open(self, port, settings):
        with self.lock:
            if port not in self.devices:
                raise DeviceUnavailable("Puerto de prueba no disponible")
            self.opens.append(port)
            return self.devices[port].open(settings)


def wait_for(condition, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("No se alcanzo el estado esperado")
