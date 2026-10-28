import json
from dataclasses import dataclass, fields
from pathlib import Path

from .errors import ValidationError


@dataclass(frozen=True)
class Settings:
    database: str = "data/microp.sqlite3"
    host: str = "127.0.0.1"
    port: int = 8001
    command_timeout: float = 4.0
    reset_delay: float = 1.5
    read_timeout: float = 0.1
    stale_after: float = 3.5
    pin_file: str = "data/access-pin.json"
    model_file: str = "data/model.json"
    transport: str = "usb"
    serial_port: str = "/dev/serial0"

    @classmethod
    def load(cls, path=None):
        data = {} if path is None else json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return cls.from_mapping(data)

    @classmethod
    def from_mapping(cls, data):
        if not isinstance(data, dict) or set(data) - {field.name for field in fields(cls)}:
            raise ValidationError("Configuracion de servidor invalida o con campos desconocidos.")
        result = cls(**data)
        if result.transport not in ('usb', 'gateway'):
            raise ValidationError('transport debe ser usb o gateway.')
        if not isinstance(result.serial_port, str) or not result.serial_port or len(result.serial_port) > 512:
            raise ValidationError('serial_port debe indicar el UART del maestro.')
        if not isinstance(result.database, str) or not result.database or not isinstance(result.host, str) or not result.host:
            raise ValidationError("database y host deben ser textos no vacios.")
        if type(result.port) is not int or not 1 <= result.port <= 65535:
            raise ValidationError("Puerto HTTP invalido.")
        if any(not isinstance(getattr(result, key), str) or not getattr(result, key) for key in ('pin_file', 'model_file')):
            raise ValidationError('pin_file y model_file deben ser rutas no vacias.')
        for key in ("command_timeout", "read_timeout", "stale_after"):
            if type(getattr(result, key)) not in (int, float) or not 0 < getattr(result, key) <= 60:
                raise ValidationError(f"{key} debe estar entre 0 y 60 segundos.")
        if type(result.reset_delay) not in (int, float) or not 0 <= result.reset_delay <= 30:
            raise ValidationError("reset_delay fuera de rango.")
        return result

