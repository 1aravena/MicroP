from dataclasses import asdict
import json
import subprocess
import sys

from backend.config import Settings
from backend.credentials import set_pin
from backend.doctor import report


def test_doctor_is_read_only_and_does_not_reveal_pin(tmp_path):
    pin_file = tmp_path / 'pin.json'
    pin = '195307'  # Credencial temporal de prueba.
    set_pin(pin_file, pin)
    settings = Settings(database=str(tmp_path / 'not-created.sqlite'), pin_file=str(pin_file), model_file=str(tmp_path / 'no-model.json'))
    result = report(settings)
    assert result['ok'] and result['records'] == {}
    assert not (tmp_path / 'not-created.sqlite').exists()
    assert pin not in json.dumps(result)
    assert any(item['name'] == 'modelo' and item['state'] == 'warning' for item in result['checks'])
    config = tmp_path / 'config.json'
    config.write_text(json.dumps(asdict(settings)), encoding='utf-8')
    process = subprocess.run([sys.executable, '-m', 'backend.doctor', '--config', str(config)], capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)['database'] == str((tmp_path / 'not-created.sqlite').resolve())


def test_gateway_without_uart_reports_unavailable_without_creating_database(tmp_path):
    settings = Settings(transport='gateway', serial_port=str(tmp_path / 'absent-uart'), database=str(tmp_path / 'not-created.sqlite'),
                        pin_file=str(tmp_path / 'no-pin'), model_file=str(tmp_path / 'no-model'))
    result = report(settings)
    assert not result['ok']
    assert any(item['name'] == 'uart' and item['state'] == 'error' for item in result['checks'])
    assert not (tmp_path / 'not-created.sqlite').exists()
