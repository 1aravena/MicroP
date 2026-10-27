"""Acceso USB real; las pruebas inyectan una fabrica alternativa."""
from collections import deque
import os

import serial
from serial.tools import list_ports

from .errors import BackendError, DeviceUnavailable


def canonical_port(port):
    if os.name == "nt":
        return port.removeprefix("\\\\.\\").upper()
    return os.path.realpath(port)


class SerialFactory:
    def ports(self):
        return [{"device": port.device, "description": port.description,
                 "serialNumber": port.serial_number, "location": port.location}
                for port in sorted(list_ports.comports())]

    def open(self, port, settings):
        available = {canonical_port(item["device"]) for item in self.ports()}
        if canonical_port(port) not in available:
            raise DeviceUnavailable("El puerto no aparece entre los dispositivos disponibles.")
        try:
            return serial.Serial(port=port, baudrate=115200, timeout=settings.read_timeout,
                                 write_timeout=settings.command_timeout, exclusive=True if os.name == "posix" else None)
        except (serial.SerialException, OSError) as error:
            raise DeviceUnavailable(f"No se pudo abrir el puerto; revisa cable, permisos y otras aplicaciones: {error}") from error


class PortRegistry:
    def __init__(self):
        import threading
        self.lock = threading.Lock()
        self.claimed = {}

    def claim(self, port, origin):
        key = canonical_port(port)
        with self.lock:
            if key in self.claimed:
                raise BackendError("Este puerto o uno de sus alias ya esta asignado.")
            self.claimed[key] = origin

    def release(self, port, origin):
        if port is not None:
            with self.lock:
                key = canonical_port(port)
                if self.claimed.get(key) == origin:
                    del self.claimed[key]


class LineFramer:
    def __init__(self, maximum=512):
        self.maximum = maximum
        self.buffer = bytearray()
        self.discarding = False
        self.ready = deque()

    def feed(self, data):
        # Se lee un bloque acotado cada vez y se vacia ready antes del siguiente.
        for byte in data:
            if byte == 10:
                if not self.discarding and self.buffer:
                    try:
                        text = self.buffer.decode("utf-8").removesuffix("\r")
                        if text:
                            self.ready.append((text, None))
                    except UnicodeDecodeError:
                        self.ready.append((None, "Linea con codificacion UTF-8 invalida."))
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                self.buffer.append(byte)
                if len(self.buffer) > self.maximum:
                    self.buffer.clear()
                    self.discarding = True
                    self.ready.append((None, "Linea demasiado larga; descartada hasta LF."))
