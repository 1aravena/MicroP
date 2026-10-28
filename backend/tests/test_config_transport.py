from dataclasses import asdict
import json

import pytest

from backend.config import Settings
from backend.errors import DeviceUnavailable, ValidationError
from backend.transport import SerialFactory


def test_settings_defaults_and_utf8_configuration(tmp_path):
    assert Settings.load().host == "127.0.0.1"
    assert Settings.load().port == 8001
    path = tmp_path / "settings.json"
    data = asdict(Settings())
    data["host"] = "0.0.0.0"
    path.write_text(json.dumps(data), encoding="utf-8-sig")
    assert Settings.load(path).host == "0.0.0.0"


@pytest.mark.parametrize("patch", [{"unknown": 1}, {"port": 0}, {"port": True}, {"command_timeout": -1},
                                  {"read_timeout": 0}, {"reset_delay": -1}, {"stale_after": float("nan")}, {"database": ""}])
def test_invalid_server_settings_are_rejected(patch):
    with pytest.raises(ValidationError):
        Settings.from_mapping({**asdict(Settings()), **patch})


def test_real_factory_only_opens_enumerated_ports_with_explicit_timeouts(monkeypatch):
    factory = SerialFactory()
    monkeypatch.setattr(factory, "ports", lambda: [{"device": "DEVICE_PORT"}])
    calls = []
    monkeypatch.setattr("backend.transport.serial.Serial", lambda **kwargs: calls.append(kwargs) or object())
    with pytest.raises(DeviceUnavailable):
        factory.open("OTHER_PORT", Settings())
    assert not calls
    factory.open("DEVICE_PORT", Settings())
    assert calls[0]["baudrate"] == 115200
    assert calls[0]["write_timeout"] == 4
    assert calls[0]["timeout"] == 0.1
    assert (calls[0]['bytesize'], calls[0]['parity'], calls[0]['stopbits']) == (8, 'N', 1)


def test_gateway_gpio_is_explicitly_configured_not_an_arbitrary_http_path(monkeypatch):
    from types import SimpleNamespace
    import os
    monkeypatch.setattr('backend.transport.os', SimpleNamespace(name='posix', path=os.path))
    factory = SerialFactory()
    monkeypatch.setattr(factory, 'ports', lambda: [])
    calls = []
    monkeypatch.setattr('backend.transport.serial.Serial', lambda **kwargs: calls.append(kwargs) or object())
    settings = Settings(transport='gateway', serial_port='/dev/serial0')
    factory.open('/dev/serial0', settings)
    assert calls[0]['port'] == '/dev/serial0' and calls[0]['exclusive']
    with pytest.raises(DeviceUnavailable):
        factory.open('/tmp/arbitrary-file', settings)
