from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from backend.errors import BackendError, CommandTimeout, ValidationError
from backend.protocol import default_config
from backend.service import AcquisitionService
from .fakes import wait_for


def capturing(service, origin):
    board = service.board(origin)
    board.submit("connect", {"port": f"{origin}_PORT"})
    board.submit("config", default_config(origin))
    result = board.submit("start")
    assert result["busy"] is False
    return board


def test_two_boards_partial_errors_duplicates_and_independent_disconnect(service, factory):
    uno = capturing(service, "UNO")
    nano = capturing(service, "NANO")
    factory.devices["UNO_PORT"].emit("@ERR,READ,HC_SR04_NO_VALID_ECHO\nUNO,1,1000,NA,NA,NA,100,1\nUNO,1,1000,20,NA,NA,100,1\nUNO,3,3000,25,NA,NA,100,0\n")
    factory.devices["NANO_PORT"].emit("NANO,1,1000,NA,1,0,NA,NA\n")
    wait_for(lambda: uno.snapshot()["sampleCount"] == 2 and nano.snapshot()["sampleCount"] == 1)
    kinds = {item["type"] for item in service.store.page("incidents")["items"]}
    assert {"GAP", "INVALID", "MISSING", "DEVICE"} <= kinds
    factory.devices["NANO_PORT"].unplug()
    wait_for(lambda: not nano.snapshot()["connected"])
    assert uno.snapshot()["phase"] == "capturing"
    assert service.store.capture(nano.snapshot()["captureId"])["status"] == "interrupted"
    events = service.store.page("incidents", capture_id=nano.snapshot()["captureId"])["items"]
    assert any(item["type"] == "TRANSPORT" and "USB retirado" in item["description"] for item in events)
    assert len(service.store.page("samples")["items"]) == 3


def test_wrong_identity_releases_port_and_does_not_configure(service, factory):
    factory.devices["UNO_PORT"].origin = "NANO"
    with pytest.raises(ValidationError):
        service.board("UNO").submit("connect", {"port": "UNO_PORT"})
    assert not service.board("UNO").snapshot()["connected"]
    assert all(not command.startswith("CONFIG") for command in factory.devices["UNO_PORT"].commands)
    service.board("NANO").submit("connect", {"port": "UNO_PORT"})
    assert service.board("NANO").snapshot()["connected"]


def test_timeout_and_busy_uno_do_not_block_nano(service, factory):
    uno, nano = capturing(service, "UNO"), capturing(service, "NANO")
    uno.submit("stop")
    factory.devices["UNO_PORT"].on_command = lambda command, _: False if command == "START" else None
    with ThreadPoolExecutor() as executor:
        failed = executor.submit(uno.submit, "start")
        wait_for(lambda: uno.snapshot()["busy"])
        with pytest.raises(BackendError, match="otro comando"):
            uno.submit("stop")
        factory.devices["NANO_PORT"].emit("NANO,1,1000,NA,1,1,NA,NA\n")
        wait_for(lambda: nano.snapshot()["sampleCount"] == 1)
        with pytest.raises(CommandTimeout):
            failed.result()
    assert uno.snapshot()["configured"] is False
    assert nano.snapshot()["phase"] == "capturing"
    uno.submit("config", default_config("UNO"))
    assert uno.snapshot()["phase"] == "configured"


def test_enable_mask_changes_exactly_after_matching_ack(service, factory):
    board = capturing(service, "UNO")
    def command(text, port):
        if text == "ENABLE,SOUND,0":
            port.emit("UNO,1,1000,20,NA,NA,100,1\n@OK,ENABLE,PIR,0\n@ERR,READ,BH1750\n@OK,ENABLE,SOUND,0\nUNO,2,2000,20,NA,NA,100,NA\n")
            return False
    factory.devices["UNO_PORT"].on_command = command
    board.submit("enable", {"sensor": "sound", "enabled": False})
    wait_for(lambda: board.snapshot()["sampleCount"] == 2)
    samples = service.store.page("samples")["items"]
    assert samples[0]["enabled"]["sound"] is True
    assert samples[1]["enabled"]["sound"] is False
    assert samples[1]["sound"] is None


def test_rejected_config_retains_confirmed_values(service, factory):
    board = service.board("UNO")
    board.submit("connect", {"port": "UNO_PORT"})
    board.submit("config", default_config("UNO"))
    def reject(text, port):
        if text.startswith("CONFIG"):
            port.emit("@ERR,CONFIG,BH1750_NOT_FOUND\n")
            return False
    factory.devices["UNO_PORT"].on_command = reject
    next_config = default_config("UNO")
    next_config["hcTrigger"] = 10
    with pytest.raises(BackendError, match="BH1750"):
        board.submit("config", next_config)
    assert board.snapshot()["config"]["hcTrigger"] == 4
    assert board.snapshot()["configured"] is False


def test_device_reset_requires_config_and_new_capture_id(service, factory):
    board = capturing(service, "UNO")
    old_id = board.snapshot()["captureId"]
    factory.devices["UNO_PORT"].emit("@READY,2,UNO\n")
    wait_for(lambda: not board.snapshot()["configured"])
    with pytest.raises(BackendError):
        board.submit("start")
    assert service.store.capture(old_id)["status"] == "interrupted"
    board.submit("config", default_config("UNO"))
    assert board.submit("start")["captureId"] != old_id


def test_stale_first_sample_and_no_history_in_memory(service, factory):
    board = capturing(service, "UNO")
    wait_for(lambda: board.snapshot()["stale"])
    assert board.snapshot()["latestSample"] is None
    for number in range(1, 31):
        factory.devices["UNO_PORT"].emit(f"UNO,{number},{number*1000},20,NA,NA,100,0\n")
    wait_for(lambda: board.snapshot()["sampleCount"] == 30)
    assert board.snapshot()["latestSample"]["sequence"] == 30
    assert "rows" not in board.state and "captures" not in board.__dict__
    assert service.store.capture(board.snapshot()["captureId"])["sampleCount"] == 30


def test_storage_failure_stops_acquisition_without_claiming_samples_saved(service, factory):
    board = capturing(service, "UNO")
    def deny_samples(action, table, *args):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_INSERT and table == "samples" else sqlite3.SQLITE_OK
    with service.store.lock:
        service.store.connection.set_authorizer(deny_samples)
    factory.devices["UNO_PORT"].emit("UNO,1,1000,20,NA,NA,100,0\n")
    wait_for(lambda: board.snapshot()["phase"] == "storage_error")
    assert board.snapshot()["sampleCount"] == 0
    assert not board.snapshot()["connected"]
    assert not service.store.health()["ok"]
    assert service.store.page("samples")["items"] == []
    assert factory.devices["UNO_PORT"].closed


def test_normal_service_restart_keeps_history_and_never_auto_connects(settings, factory):
    first = AcquisitionService(settings, factory)
    board = capturing(first, "UNO")
    factory.devices["UNO_PORT"].emit("UNO,1,1000,20,NA,NA,100,0\n")
    wait_for(lambda: board.snapshot()["sampleCount"] == 1)
    capture_id = board.snapshot()["captureId"]
    first.close()
    opens = len(factory.opens)
    second = AcquisitionService(settings, factory)
    try:
        assert len(factory.opens) == opens
        assert all(not state["connected"] for state in second.snapshots())
        assert second.store.capture(capture_id)["status"] == "stopped"
        assert second.store.page("samples")["items"][0]["captureId"] == capture_id
        new_board = capturing(second, "UNO")
        assert new_board.snapshot()["captureId"] != capture_id
    finally:
        second.close()


def test_start_ack_and_first_sample_in_same_usb_chunk(service, factory):
    board = service.board("UNO")
    board.submit("connect", {"port": "UNO_PORT"})
    board.submit("config", default_config("UNO"))
    def immediate(command, port):
        if command == "START":
            port.emit("@OK,START\nUNO,1,1000,20,NA,NA,100,0\n")
            return False
    factory.devices["UNO_PORT"].on_command = immediate
    board.submit("start")
    wait_for(lambda: board.snapshot()["sampleCount"] == 1)
    assert board.snapshot()["latestSample"]["captureId"] == board.snapshot()["captureId"]


def test_shutdown_during_pending_command_releases_worker_and_database(settings, factory):
    service = AcquisitionService(settings, factory)
    board = capturing(service, "UNO")
    board.submit("stop")
    factory.devices["UNO_PORT"].on_command = lambda command, _: False if command == "START" else None
    with ThreadPoolExecutor() as executor:
        pending = executor.submit(board.submit, "start")
        wait_for(lambda: board.snapshot()["busy"])
        service.close()
        with pytest.raises(BackendError):
            pending.result(timeout=1)
    assert not board.thread.is_alive()
    assert factory.devices["UNO_PORT"].closed
    again = AcquisitionService(settings, factory)
    again.close()
