from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .errors import BackendError, DeviceUnavailable
from .service import AcquisitionService

Origin = Literal["UNO", "NANO"]
Sensor = Literal["hc", "pir", "radar", "lux", "sound"]
Order = Literal["asc", "desc"]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Enabled(StrictModel):
    hc: bool
    pir: bool
    radar: bool
    lux: bool
    sound: bool


Pin = Annotated[int, Field(ge=0, le=255)]


class BoardConfig(StrictModel):
    origin: Origin
    hcTrigger: Pin
    hcEcho: Pin
    pirPin: Pin
    radarPin: Pin
    soundPin: Pin
    enabled: Enabled


class ConnectionRequest(StrictModel):
    port: str = Field(min_length=1, max_length=512)


class EnableRequest(StrictModel):
    enabled: bool


def get_service(request: Request):
    return request.app.state.service


Service = Annotated[AcquisitionService, Depends(get_service)]
Limit = Annotated[int, Query(ge=1, le=500)]
Cursor = Annotated[int, Query(ge=0)]


def create_app(settings=None, factory=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        # El import de la API no abre puertos ni crea una base.
        service = AcquisitionService(settings, factory)
        app.state.service = service
        try:
            yield
        finally:
            service.close()

    # OpenAPI JSON disponible. No se depende de un CDN para utilizar la API sin internet.
    app = FastAPI(title="MicroP · Grupo C", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)

    web_root = Path(__file__).resolve().parents[1]

    @app.get("/", include_in_schema=False)
    def panel():
        return FileResponse(web_root / "panel.html", headers={"Cache-Control": "no-cache"})

    # Solo recursos publicos. Nunca montar la raiz del repositorio ni data/.
    app.mount("/css", StaticFiles(directory=web_root / "css"), name="css")
    app.mount("/js", StaticFiles(directory=web_root / "js"), name="js")

    @app.exception_handler(BackendError)
    async def backend_error(_, error):
        return JSONResponse(status_code=error.status_code, content={"detail": str(error)})

    prefix = "/api/v1"

    @app.get(prefix + "/health")
    def health(service: Service):
        storage = service.store.health()
        return JSONResponse(status_code=200 if storage["ok"] else 503,
                            content={"ok": storage["ok"], "service": "microp-backend", "protocolVersion": 2,
                                     "storage": storage, "boardsConnected": sum(item["connected"] for item in service.snapshots())})

    @app.get(prefix + "/ports")
    def ports(service: Service):
        try:
            return {"items": service.factory.ports()}
        except OSError as error:
            raise DeviceUnavailable(f"No se pudieron enumerar puertos: {error}") from error

    @app.get(prefix + "/boards")
    def boards(service: Service):
        return {"items": service.snapshots()}

    @app.post(prefix + "/boards/{origin}/connect")
    def connect(origin: Origin, body: ConnectionRequest, service: Service):
        return service.board(origin).submit("connect", body.model_dump())

    @app.post(prefix + "/boards/{origin}/disconnect")
    def disconnect(origin: Origin, service: Service):
        return service.board(origin).submit("disconnect")

    @app.put(prefix + "/boards/{origin}/config")
    def configure(origin: Origin, body: BoardConfig, service: Service):
        return service.board(origin).submit("config", body.model_dump())

    @app.post(prefix + "/boards/{origin}/start")
    def start(origin: Origin, service: Service):
        return service.board(origin).submit("start")

    @app.post(prefix + "/boards/{origin}/stop")
    def stop(origin: Origin, service: Service):
        return service.board(origin).submit("stop")

    @app.put(prefix + "/boards/{origin}/sensors/{sensor}")
    def enable(origin: Origin, sensor: Sensor, body: EnableRequest, service: Service):
        return service.board(origin).submit("enable", {"sensor": sensor, "enabled": body.enabled})

    @app.get(prefix + "/captures")
    def captures(service: Service, origin: Origin | None = None, after_id: Cursor = 0,
                 limit: Limit = 100, order: Order = "asc"):
        return service.store.page("captures", origin=origin, after_id=after_id, limit=limit, order=order)

    @app.get(prefix + "/captures/{capture_id}")
    def capture(capture_id: UUID, service: Service):
        return service.store.capture(str(capture_id))

    @app.get(prefix + "/samples")
    def samples(service: Service, origin: Origin | None = None, capture_id: UUID | None = None,
                after_id: Cursor = 0, limit: Limit = 100, order: Order = "asc"):
        if capture_id:
            service.store.capture(str(capture_id))
        return service.store.page("samples", origin=origin, capture_id=str(capture_id) if capture_id else None,
                                  after_id=after_id, limit=limit, order=order)

    @app.get(prefix + "/incidents")
    def incidents(service: Service, origin: Origin | None = None, capture_id: UUID | None = None,
                  after_id: Cursor = 0, limit: Limit = 100, order: Order = "asc"):
        if capture_id:
            service.store.capture(str(capture_id))
        return service.store.page("incidents", origin=origin, capture_id=str(capture_id) if capture_id else None,
                                  after_id=after_id, limit=limit, order=order)

    @app.get(prefix + "/captures/{capture_id}/export.csv")
    def export_capture(capture_id: UUID, service: Service):
        service.store.capture(str(capture_id))
        chunks = service.store.export("samples", capture_id=str(capture_id))
        return StreamingResponse(chunks, media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="mediciones-{capture_id}.csv"'})

    @app.get(prefix + "/incidents/export.csv")
    def export_incidents(service: Service, origin: Origin | None = None, capture_id: UUID | None = None):
        if capture_id:
            service.store.capture(str(capture_id))
        return StreamingResponse(service.store.export("incidents", origin=origin, capture_id=str(capture_id) if capture_id else None),
                                 media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": 'attachment; filename="incidencias.csv"'})

    return app

