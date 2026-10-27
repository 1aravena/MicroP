import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def test_real_cli_starts_without_hardware_and_responds_over_http(tmp_path):
    root = Path(__file__).resolve().parents[2]
    with socket.socket() as socket_probe:
        socket_probe.bind(("127.0.0.1", 0))
        port = socket_probe.getsockname()[1]
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    process = subprocess.Popen([sys.executable, "-m", "backend", "--port", str(port), "--database", str(tmp_path / "cli.sqlite")],
                               cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **options)
    try:
        endpoint = f"http://127.0.0.1:{port}/api/v1"
        deadline = time.monotonic() + 10
        health = None
        while time.monotonic() < deadline and process.poll() is None:
            try:
                with urlopen(endpoint + "/health", timeout=0.5) as response:
                    health = json.load(response)
                    break
            except OSError:
                time.sleep(0.05)
        assert health is not None, "El backend CLI no respondio"
        assert health["ok"] and health["boardsConnected"] == 0
        try:
            urlopen(Request(endpoint + "/boards/UNO/start", data=b"", method="POST"), timeout=2)
        except HTTPError as error:
            assert error.code == 409
        else:
            raise AssertionError("El servidor inicio sin conexion/configuracion")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        output = process.stdout.read().decode("utf-8", errors="replace")
        process.stdout.close()
        assert "Traceback" not in output, output
