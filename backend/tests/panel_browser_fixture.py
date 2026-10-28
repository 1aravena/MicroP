"""Servidor exclusivo de QA visual. Nunca importado por backend de produccion.

Ejecutar: python -m backend.tests.panel_browser_fixture --port 8012
Las mediciones y las rutas /test/ son SIMULADAS, no datos del prototipo.
"""
import argparse
from math import sin
from pathlib import Path
import tempfile
import threading

from fastapi.responses import HTMLResponse
import uvicorn

from backend.api import create_app
from backend.config import Settings
from backend.protocol import default_config
from backend.credentials import set_pin
from .fakes import FakeFactory


def fixture_app(database):
    factory = FakeFactory()
    states = {origin: {"running": False, "paused": False, "sequence": 0, "config": default_config(origin)}
              for origin in ("UNO", "NANO")}
    lock = threading.Lock()

    def command(text, port):
        kind, *args = text.split(",")
        with lock:
            state = states[port.origin]
            if kind == "START":
                state.update(running=True, paused=False, sequence=0)
            elif kind == "STOP":
                state["running"] = False
            elif kind == "CONFIG":
                state["config"]["enabled"] = dict(zip(("hc", "pir", "radar", "lux", "sound"), map(lambda x: x == "1", args[5:])))
            elif kind == "ENABLE":
                state["config"]["enabled"][args[0].lower()] = args[1] == "1"

    for port in factory.devices.values():
        port.on_command = command
    pin_path = Path(database).parent / 'qa-pin.json'
    set_pin(pin_path, '804291')  # Credencial desechable de este fixture, no un PIN de produccion.
    app = create_app(Settings(database=database, reset_delay=0, pin_file=str(pin_path),
                              model_file=str(Path(database).parent / 'qa-model.json')), factory)
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) != "/"]

    @app.get("/")
    def page():
        html = (Path(__file__).resolve().parents[2] / "panel.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace('<main class="app-shell">', '<main class="app-shell"><p role="note">PRUEBA VISUAL · PERIFÉRICOS SIMULADOS</p>'))

    def emit(origin):
        state = states[origin]
        state["sequence"] += 1
        n = state["sequence"]
        enabled = state["config"]["enabled"]
        values = {"hc": f"{45 + 20 * sin(n / 4):.2f}", "pir": str((n // 3) % 2),
                  "radar": str((n // 4) % 2), "lux": f"{120 + n % 30:.2f}", "sound": str(n % 7 == 0).replace("True", "1").replace("False", "0")}
        row = [values[key] if enabled[key] else "NA" for key in ("hc", "pir", "radar", "lux", "sound")]
        factory.devices[f"{origin}_PORT"].emit(f"{origin},{n},{n * 1000},{','.join(row)}\n")

    @app.post("/test/unplug/{origin}")
    def unplug(origin: str):
        with lock:
            states[origin]["running"] = False
            factory.devices[f"{origin}_PORT"].unplug()
        return {"simulated": True}

    @app.post("/test/pause/{origin}")
    def pause(origin: str):
        with lock:
            states[origin]["paused"] = not states[origin]["paused"]
        return {"simulated": True}

    @app.post("/test/fill/{origin}")
    def fill(origin: str, count: int = 325):
        with lock:
            for _ in range(min(max(count, 0), 500)):
                emit(origin)
        return {"simulated": True}

    def generate():
        while not app.state.fixture_stop.wait(1):
            with lock:
                for origin, state in states.items():
                    if state["running"] and not state["paused"]:
                        emit(origin)

    app.state.fixture_stop = threading.Event()
    original_lifespan = app.router.lifespan_context
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            worker = threading.Thread(target=generate, daemon=True)
            worker.start()
            try:
                yield
            finally:
                app.state.fixture_stop.set()
                worker.join(timeout=2)
    app.router.lifespan_context = lifespan
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="microp-panel-qa-") as folder:
        uvicorn.run(fixture_app(str(Path(folder) / "qa.sqlite3")), host="127.0.0.1", port=args.port, access_log=False)
