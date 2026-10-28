"""PIN de maqueta: nunca forma parte del protocolo, del log ni de SQLite."""
import argparse
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from .errors import ValidationError

ITERATIONS = 600000


def valid_pin(pin):
    return isinstance(pin, str) and re.fullmatch(r'[0-9]{6}', pin) is not None


def set_pin(path, pin):
    if not valid_pin(pin):
        raise ValidationError('El PIN debe contener exactamente seis digitos.')
    salt = secrets.token_bytes(16)
    data = {'version': 1, 'algorithm': 'pbkdf2-sha256', 'iterations': ITERATIONS,
            'salt': salt.hex(), 'digest': hashlib.pbkdf2_hmac('sha256', pin.encode(), salt, ITERATIONS).hex()}
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=destination.parent, delete=False) as file:
            temporary = Path(file.name)
            os.chmod(file.name, 0o600)
            json.dump(data, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class PinVerifier:
    def __init__(self, path):
        self.record = None
        self.error = 'PIN no configurado. Configuralo en terminal y reinicia el backend.'
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            if (data['version'] != 1 or data['algorithm'] != 'pbkdf2-sha256'
                    or type(data['iterations']) is not int or not ITERATIONS <= data['iterations'] <= 2000000
                    or len(bytes.fromhex(data['salt'])) != 16 or len(bytes.fromhex(data['digest'])) != 32):
                raise ValueError()
            self.record = data
            self.error = ''
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            self.error = 'Configuracion privada del PIN invalida; vuelve a configurarlo en terminal.'

    def verify(self, pin):
        if not self.record or not valid_pin(pin):
            return False
        data = self.record
        derived = hashlib.pbkdf2_hmac('sha256', pin.encode(), bytes.fromhex(data['salt']), data['iterations'])
        return hmac.compare_digest(derived, bytes.fromhex(data['digest']))


def main():
    parser = argparse.ArgumentParser(description='Configura un PIN de seis digitos exclusivamente de demostracion. Reiniciar backend despues.')
    parser.add_argument('--file', default='data/access-pin.json')
    args = parser.parse_args()
    try:
        pin = getpass.getpass('Nuevo PIN de prueba (6 digitos): ')
        if pin != getpass.getpass('Repite el PIN: '):
            raise ValidationError('Los valores no coinciden.')
        set_pin(args.file, pin)
        print('PIN configurado. Reinicia el backend para utilizarlo.')
    except (ValidationError, OSError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
