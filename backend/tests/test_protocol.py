from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.errors import ValidationError
from backend.protocol import default_config, matches_ack, parse_identity, parse_sample, serialize_config
from backend.transport import LineFramer, PortRegistry

CASES = json.loads((Path(__file__).resolve().parents[2] / "tests/fixtures/protocol-v2.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("item", CASES["identities"])
def test_shared_identities(item):
    if item["valid"]:
        assert parse_identity(item["line"], item["origin"])["version"] == 2
    else:
        with pytest.raises(ValidationError):
            parse_identity(item["line"], item["origin"])


@pytest.mark.parametrize("item", CASES["configs"])
def test_shared_configs(item):
    config = default_config(item["origin"])
    patch = deepcopy(item["patch"])
    config["enabled"].update(patch.pop("enabled", {}))
    config.update(patch)
    if item["valid"]:
        assert serialize_config(config) == item["command"]
    else:
        with pytest.raises(ValidationError):
            serialize_config(config)


@pytest.mark.parametrize("item", CASES["samples"])
def test_shared_samples(item):
    config = default_config(item["origin"])
    for key in item.get("disabled", []):
        config["enabled"][key] = False
    if item["valid"]:
        sample = parse_sample(item["line"], config)
        for key, value in item["expected"].items():
            assert sample[key] == value
    else:
        with pytest.raises(ValidationError):
            parse_sample(item["line"], config)


def test_fragmentation_overflow_and_encoding():
    framer = LineFramer()
    framer.feed(b"@OK,IN")
    assert not framer.ready
    framer.feed(b"FO,2,UNO\r\n" + b"X" * 600)
    framer.feed(b"NOT_A_NEW_LINE\n\xff\n@OK,STOP\n")
    packets = list(framer.ready)
    assert packets[0] == ("@OK,INFO,2,UNO", None)
    assert packets[1][1] is not None and packets[2][1] is not None
    assert packets[3] == ("@OK,STOP", None)
    assert len(packets) == 4
    assert len(framer.buffer) == 0


def test_ack_requires_exact_command_sensor_and_value():
    assert matches_ack("ENABLE,SOUND,0", "@OK,ENABLE,SOUND,0")
    assert not matches_ack("ENABLE,SOUND,0", "@OK,ENABLE,PIR,0")
    assert not matches_ack("ENABLE,SOUND,0", "@OK,ENABLE,SOUND,1")
    assert not matches_ack("STOP", "@OK,STOPPED")
    assert not matches_ack("START", "@OK,START,EXTRA")


def test_registry_rejects_aliases_and_does_not_release_other_owner(monkeypatch):
    monkeypatch.setattr("backend.transport.canonical_port", lambda name: name.replace("ALIAS", "PORT"))
    registry = PortRegistry()
    registry.claim("UNO_PORT", "UNO")
    from backend.errors import BackendError
    with pytest.raises(BackendError):
        registry.claim("UNO_ALIAS", "NANO")
    registry.release("UNO_ALIAS", "NANO")
    with pytest.raises(BackendError):
        registry.claim("UNO_PORT", "NANO")
    registry.release("UNO_PORT", "UNO")
    registry.claim("UNO_ALIAS", "NANO")
