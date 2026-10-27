"""Reglas equivalentes a js/protocol.js. Protocolo en docs/protocolo-v2.md."""
import math
import re

from .errors import ValidationError

VERSION = 2
ROLES = ("UNO", "NANO")
SENSOR_KEYS = ("hc", "pir", "radar", "lux", "sound")
SENSOR_ORIGIN = {"hc": "UNO", "lux": "UNO", "sound": "UNO", "pir": "NANO", "radar": "NANO"}
PIN_ROLES = (("hc", "hcTrigger"), ("hc", "hcEcho"), ("pir", "pirPin"), ("radar", "radarPin"), ("sound", "soundPin"))
SENSOR_COMMANDS = {"hc": "HC", "pir": "PIR", "radar": "RADAR", "lux": "LUX", "sound": "SOUND"}
FIELDS = ("distanceCm", "pir", "radar", "lux", "sound")
WIRE_HEADER = "origen,secuencia,tiempo_ms,distancia_cm,pir_estado,radar_estado,lux,sonido_estado"
CSV_HEADER = f"fecha_hora_recepcion,captura_id,{WIRE_HEADER}"
INCIDENT_HEADER = "fecha_hora,origen,tipo,descripcion"


def check_origin(origin):
    if origin not in ROLES:
        raise ValidationError("Origen desconocido; usa UNO o NANO.")


def default_config(origin):
    check_origin(origin)
    return {"origin": origin, "hcTrigger": 4, "hcEcho": 5, "pirPin": 6, "radarPin": 7, "soundPin": 8,
            "enabled": {key: SENSOR_ORIGIN[key] == origin for key in SENSOR_KEYS}}


def validate_config(config):
    if not isinstance(config, dict):
        raise ValidationError("La configuracion debe ser un objeto.")
    origin = config.get("origin")
    check_origin(origin)
    enabled = config.get("enabled")
    if not isinstance(enabled, dict) or set(enabled) != set(SENSOR_KEYS):
        raise ValidationError("enabled debe declarar los cinco sensores.")
    expected = {"origin", "enabled", *(field for _, field in PIN_ROLES)}
    if set(config) != expected:
        raise ValidationError("Campos de configuracion incompletos o desconocidos.")
    for key in SENSOR_KEYS:
        if type(enabled[key]) is not bool:
            raise ValidationError(f"Estado invalido: {key}.")
        if enabled[key] and SENSOR_ORIGIN[key] != origin:
            raise ValidationError(f"{key} no pertenece a {origin}.")
    used = set()
    for sensor, field in PIN_ROLES:
        pin = config[field]
        if type(pin) is not int or not 0 <= pin <= 255:
            raise ValidationError(f"{field} debe ser entero 0..255.")
        if enabled[sensor]:
            if not 2 <= pin <= 12 or pin in used:
                raise ValidationError(f"Pin invalido o repetido: {field}. Usa D2 a D12.")
            used.add(pin)
    return config


def serialize_config(config):
    validate_config(config)
    values = [config[field] for field in ("hcTrigger", "hcEcho", "pirPin", "radarPin", "soundPin")]
    return ",".join(map(str, ["CONFIG", *values, *(int(config["enabled"][key]) for key in SENSOR_KEYS)]))


def parse_identity(line, origin):
    check_origin(origin)
    fields = line.split(",")
    if len(fields) != 4 or fields[:3] != ["@OK", "INFO", str(VERSION)]:
        raise ValidationError("Firmware incompatible; se requiere protocolo 2.")
    if fields[3] != origin:
        raise ValidationError(f"Se esperaba {origin}; el firmware declara {fields[3]}.")
    return {"origin": origin, "version": VERSION}


def unsigned(text, label, positive=False):
    if not re.fullmatch(r"[0-9]+", text):
        raise ValidationError(f"{label} debe ser un entero uint32.")
    value = int(text)
    if value > 0xFFFFFFFF or (positive and value == 0):
        raise ValidationError(f"{label} fuera de rango.")
    return value


def parse_sample(line, config):
    tokens = line.split(",")
    if len(tokens) != 8:
        raise ValidationError("La muestra debe contener ocho columnas.")
    origin = tokens[0]
    if origin not in ROLES or origin != config["origin"]:
        raise ValidationError("Origen incorrecto en la muestra.")
    values = []
    for key, token in zip(SENSOR_KEYS, tokens[3:]):
        if SENSOR_ORIGIN[key] != origin or not config["enabled"][key]:
            if token != "NA":
                raise ValidationError(f"{key} debe ser NA para este origen o sensor desactivado.")
            value = None
        elif token == "NA":
            value = None
        elif key in ("pir", "radar", "sound"):
            if token not in ("0", "1"):
                raise ValidationError(f"{key} debe ser 0 o 1.")
            value = int(token)
        else:
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", token):
                raise ValidationError(f"{key} no es un numero valido.")
            value = float(token)
            if not math.isfinite(value) or (key == "hc" and not 2 <= value <= 400):
                raise ValidationError(f"{key} fuera de rango.")
        values.append(value)
    return {"raw": line, "origin": origin, "sequence": unsigned(tokens[1], "secuencia", True),
            "timeMs": unsigned(tokens[2], "tiempo_ms"), **dict(zip(FIELDS, values))}


def matches_ack(command, line):
    sent = command.split(",")
    received = line.split(",")
    if received[:2] != ["@OK", sent[0]]:
        return False
    if sent[0] == "INFO":
        return len(received) == 4
    if sent[0] == "ENABLE":
        return len(received) == 4 and received[2:] == sent[1:]
    return len(received) == 2

