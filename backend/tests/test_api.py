from uuid import uuid4

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.protocol import default_config
from .fakes import wait_for


def start(client, origin):
    response = client.post(f"/api/v1/boards/{origin}/connect", json={"port": f"{origin}_PORT"})
    assert response.status_code == 200, response.text
    response = client.put(f"/api/v1/boards/{origin}/config", json=default_config(origin))
    assert response.status_code == 200, response.text
    response = client.post(f"/api/v1/boards/{origin}/start")
    assert response.status_code == 200, response.text
    return response.json()["captureId"]


def test_api_complete_cycle_and_csv_survive_restart(settings, factory):
    app = create_app(settings, factory)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["boardsConnected"] == 0
        assert len(client.get("/api/v1/ports").json()["items"]) == 2
        assert client.get("/openapi.json").status_code == 200
        capture = start(client, "UNO")
        start(client, "NANO")
        factory.devices["UNO_PORT"].emit("UNO,1,1000,NA,NA,NA,100,0\n")
        factory.devices["NANO_PORT"].emit("NANO,1,1000,NA,1,0,NA,NA\n")
        wait_for(lambda: len(client.get("/api/v1/samples").json()["items"]) == 2)
        partial = client.get("/api/v1/samples", params={"origin": "UNO", "capture_id": capture}).json()["items"][0]
        assert partial["distanceCm"] is None and partial["lux"] == 100
        assert partial["enabled"]["hc"] is True
        csv = client.get(f"/api/v1/captures/{capture}/export.csv")
        assert csv.status_code == 200
        assert "attachment" in csv.headers["content-disposition"]
        assert "UNO,1,1000,NA,NA,NA,100,0" in csv.text
        assert "NANO,1" not in csv.text
        assert client.get("/api/v1/incidents/export.csv").status_code == 200
        assert client.post("/api/v1/boards/UNO/stop").status_code == 200
        assert client.get(f"/api/v1/captures/{capture}").json()["status"] == "stopped"
        assert client.post("/api/v1/boards/UNO/disconnect").status_code == 200
        assert client.get("/api/v1/boards").json()["items"][1]["phase"] == "capturing"
    with TestClient(create_app(settings, factory)) as client:
        assert client.get(f"/api/v1/captures/{capture}").json()["sampleCount"] == 1
        assert all(not item["connected"] for item in client.get("/api/v1/boards").json()["items"])


def test_api_validation_states_and_limits(settings, factory):
    with TestClient(create_app(settings, factory)) as client:
        assert client.post("/api/v1/boards/UNO/start").status_code == 409
        assert client.post("/api/v1/boards/INVALID/connect", json={"port": "UNO_PORT"}).status_code == 422
        assert client.get("/api/v1/samples?limit=501").status_code == 422
        assert client.get("/api/v1/captures?after_id=-1").status_code == 422
        assert client.get(f"/api/v1/captures/{uuid4()}/export.csv").status_code == 404
        assert client.post("/api/v1/boards/UNO/connect", json={"port": "UNO_PORT"}).status_code == 200
        bad = default_config("UNO")
        bad["hcTrigger"] = "4"
        assert client.put("/api/v1/boards/UNO/config", json=bad).status_code == 422
        bad["hcTrigger"] = 5
        assert client.put("/api/v1/boards/UNO/config", json=bad).status_code == 422
        assert client.put("/api/v1/boards/UNO/sensors/sound", json={"enabled": 1}).status_code == 422
        assert client.put("/api/v1/boards/UNO/config", json=default_config("UNO")).status_code == 200
        assert client.post("/api/v1/boards/UNO/start").status_code == 200
        assert client.post("/api/v1/boards/UNO/start").status_code == 409
        assert client.put("/api/v1/boards/UNO/config", json=default_config("UNO")).status_code == 409
        assert client.get("/api/v1/captures?origin=NANO").json()["items"] == []


def test_http_client_disappearance_does_not_stop_capture(settings, factory):
    with TestClient(create_app(settings, factory)) as client:
        capture = start(client, "UNO")
        factory.devices["UNO_PORT"].emit("UNO,1,1000,20,NA,NA,100,0\n")
        service = client.app.state.service
        wait_for(lambda: service.board("UNO").snapshot()["sampleCount"] == 1)
        # Sin peticiones HTTP durante la segunda muestra: el actor sigue adquiriendo.
        factory.devices["UNO_PORT"].emit("UNO,2,2000,30,NA,NA,100,1\n")
        wait_for(lambda: service.board("UNO").snapshot()["sampleCount"] == 2)
        assert client.get(f"/api/v1/captures/{capture}").json()["sampleCount"] == 2


def test_api_enable_stop_and_pagination(settings, factory):
    with TestClient(create_app(settings, factory)) as client:
        start(client, "UNO")
        response = client.put("/api/v1/boards/UNO/sensors/sound", json={"enabled": False})
        assert response.status_code == 200
        assert response.json()["config"]["enabled"]["sound"] is False
        factory.devices["UNO_PORT"].emit("UNO,1,1000,20,NA,NA,100,NA\nUNO,2,2000,30,NA,NA,100,NA\n")
        wait_for(lambda: client.get("/api/v1/boards").json()["items"][0]["sampleCount"] == 2)
        first = client.get("/api/v1/samples?limit=1").json()
        second = client.get("/api/v1/samples", params={"after_id": first["nextCursor"], "limit": 1}).json()
        assert first["items"][0]["sequence"] == 1
        assert second["items"][0]["sequence"] == 2
        assert client.post("/api/v1/boards/UNO/stop").status_code == 200
