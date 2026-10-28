"""Diagnostico de despliegue de solo lectura; no abre UART ni migra SQLite."""
import argparse
import json
import os
from pathlib import Path
import platform
import socket
import sqlite3
import sys

from .config import Settings
from .credentials import PinVerifier
from .ml_runtime import ModelRuntime
from .errors import BackendError


def report(settings):
    checks = []
    def check(name, ok, detail, optional=False):
        checks.append({'name': name, 'state': 'ok' if ok else 'warning' if optional else 'error', 'detail': detail})
    model_path = Path('/proc/device-tree/model')
    board = model_path.read_text(errors='replace').rstrip('\0') if model_path.exists() else 'Equipo sin identificacion Raspberry'
    check('python', sys.version_info >= (3, 11), platform.python_version())
    check('equipo', 'Raspberry Pi' in board, board, optional=True)
    if settings.transport == 'gateway':
        port = Path(settings.serial_port)
        check('uart', port.exists() and os.access(port, os.R_OK | os.W_OK),
              f'{port}: debe existir y permitir lectura/escritura al usuario del backend.')
        command_line = Path('/proc/cmdline')
        aliases = {'serial0', 'ttyAMA0', 'ttyS0', port.name, port.resolve().name}
        consoles = command_line.read_text().split() if command_line.exists() else []
        conflict = any(token.startswith('console=') and token.split('=', 1)[1].split(',')[0] in aliases for token in consoles)
        check('consola_uart', not conflict, 'La consola de Linux debe estar deshabilitada en el UART de datos.')
    destination = Path(settings.database).resolve()
    parent = destination.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    check('almacenamiento', os.access(destination if destination.exists() else parent, os.W_OK), str(destination))
    counts = {}
    if destination.is_file():
        try:
            with sqlite3.connect(destination.as_uri() + '?mode=ro', uri=True, timeout=0.5) as db:
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in ('captures', 'samples', 'incidents', 'collection_sessions', 'trials', 'observations', 'ml_predictions'):
                    counts[table] = db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] if table in tables else None
        except sqlite3.Error as error:
            check('sqlite', False, str(error))
    pin = PinVerifier(settings.pin_file)
    check('pin', pin.record is not None, pin.error or 'Configurado; no se muestra la credencial.', optional=True)
    model = ModelRuntime(settings.model_file)
    check('modelo', model.state == 'ready', model.error or 'JSON real validado.', optional=True)
    return {'ok': not any(item['state'] == 'error' for item in checks), 'hostname': socket.gethostname(),
            'platform': platform.system(), 'transport': settings.transport, 'database': str(destination),
            'records': counts, 'checks': checks,
            'notice': 'Este diagnostico no comprueba cableado, sensores, LED ni comunicacion fisica.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', help='Configuracion del backend; para Raspberry, backend/config.raspberry.json')
    args = parser.parse_args()
    try:
        result = report(Settings.load(args.config))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['ok'] else 1
    except (BackendError, ValueError, OSError) as error:
        parser.exit(1, f'No se pudo diagnosticar: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
