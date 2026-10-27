import csv
import io

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.protocol import default_config, parse_sample


def populate(store, origin, count):
    config = default_config(origin)
    capture = store.create_capture(origin, config)
    for seq in range(1, count + 1):
        line = (f"UNO,{seq},{seq * 1000},20,NA,NA,100,0" if origin == "UNO"
                else f"NANO,{seq},{seq * 1000},NA,1,0,NA,NA")
        store.add_sample(capture, parse_sample(line, config), config["enabled"], "2026-10-27T12:00:00.000Z")
    return capture


def test_panel_serves_only_public_resources(settings, factory):
    with TestClient(create_app(settings, factory)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'src="js/panel.js"' in page.text
        assert client.get("/css/styles.css").status_code == 200
        assert client.get("/js/protocol.js").status_code == 200
        for path in ("/.git/config", "/data/microp.sqlite3", "/backend/config.example.json",
                     "/.venv/pyvenv.cfg", "/requirements.txt", "/js/%2e%2e/backend/config.py",
                     "/api/v1/unknown"):
            assert client.get(path).status_code == 404
        assert client.get("/api/v1/health").json()["ok"]
        assert not factory.opens


def test_recent_samples_filtered_pagination_and_complete_export(settings, factory):
    with TestClient(create_app(settings, factory)) as client:
        store = client.app.state.service.store
        capture = populate(store, "UNO", 325)
        populate(store, "NANO", 2)
        recent = client.get("/api/v1/samples", params={"capture_id": capture, "order": "desc", "limit": 300}).json()
        assert [x["sequence"] for x in recent["items"]] == list(range(325, 25, -1))
        older = client.get("/api/v1/samples", params={"capture_id": capture, "order": "desc",
                                                      "after_id": recent["nextCursor"], "limit": 300}).json()
        assert [x["sequence"] for x in older["items"]] == list(range(25, 0, -1))
        assert client.get("/api/v1/samples").json()["items"][0]["sequence"] == 1
        assert client.get("/api/v1/samples?origin=NANO&order=desc").json()["items"][0]["sequence"] == 2
        contents = client.get(f"/api/v1/captures/{capture}/export.csv").text
        rows = list(csv.reader(io.StringIO(contents.lstrip("\ufeff"))))
        assert len(rows) == 326
        assert rows[1][3] == "1" and rows[-1][3] == "325"


@pytest.mark.parametrize("table", ["captures", "incidents"])
def test_descending_pages_keep_numeric_cursor_and_filters(settings, factory, table):
    with TestClient(create_app(settings, factory)) as client:
        store = client.app.state.service.store
        uno = populate(store, "UNO", 0)
        populate(store, "NANO", 0)
        newest = populate(store, "UNO", 0)
        first = client.get(f"/api/v1/{table}?origin=UNO&order=desc&limit=1").json()
        second = client.get(f"/api/v1/{table}", params={"origin": "UNO", "order": "desc", "limit": 1,
                                                     "after_id": first["nextCursor"]}).json()
        assert isinstance(first["nextCursor"], int)
        key = "id" if table == "captures" else "captureId"
        assert first["items"][0][key] == newest
        assert second["items"][0][key] == uno
        empty = client.get(f"/api/v1/{table}", params={"origin": "UNO", "order": "desc",
                                                     "after_id": second["nextCursor"]}).json()
        assert empty["items"] == [] and empty["nextCursor"] == second["nextCursor"]
        assert client.get(f"/api/v1/{table}?order=invalid").status_code == 422


def test_order_validation_and_empty_window(settings, factory):
    with TestClient(create_app(settings, factory)) as client:
        assert client.get("/api/v1/samples?order=desc").json() == {"items": [], "nextCursor": 0}
        assert client.get("/api/v1/samples?order=invalid").status_code == 422
        with pytest.raises(ValueError):
            client.app.state.service.store.page("samples", order="desc; DROP TABLE samples")
