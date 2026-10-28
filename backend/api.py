from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .errors import BackendError, DeviceUnavailable
from .service import AcquisitionService
from .dataset import export_dataset
from .access import AccessFailure

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


class SessionRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    responsible: str = Field(min_length=1, max_length=120)
    partition: Literal['train', 'test']
    source: Literal['real', 'simulated']
    conditions: str = Field(min_length=1, max_length=2000)
    notes: str = Field(default='', max_length=2000)


class TrialRequest(StrictModel):
    scenario: str = Field(min_length=1, max_length=64)
    notes: str = Field(default='', max_length=2000)


class ReviewRequest(StrictModel):
    confirmed: bool
    notes: str = Field(default='', max_length=2000)


class AccessRequest(StrictModel):
    requestId: str = Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    pin: str = Field(pattern=r'^[0-9]{6}$', repr=False, json_schema_extra={'writeOnly': True})


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
        body, headers = {'detail': str(error)}, {}
        if isinstance(error, AccessFailure):
            body['attempt'] = error.attempt
            if error.retry_after:
                headers['Retry-After'] = str(error.retry_after)
        return JSONResponse(status_code=error.status_code, content=body, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # No devolver input, cuerpo ni ctx: pueden contener el PIN.
        if request.url.path.startswith('/api/v1/access/'):
            return JSONResponse(status_code=422, content={'detail': 'Solicitud de acceso invalida. Revisa el UUID y el PIN de seis digitos.'})
        details = [{'loc': item['loc'], 'type': item['type'], 'msg': 'Solicitud invalida; revisa el campo indicado.'}
                   for item in error.errors()]
        return JSONResponse(status_code=422, content={'detail': details})

    prefix = "/api/v1"

    def check_access_origin(request):
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            raise AccessFailure('El acceso se solicita desde el panel servido por este backend.', 403)

    @app.get(prefix + '/access/status')
    def access_status(service: Service):
        return service.access.status()

    @app.post(prefix + '/access/enable')
    def access_enable(request: Request, service: Service):
        check_access_origin(request)
        return service.access.enable()

    @app.post(prefix + '/access/disable')
    def access_disable(request: Request, service: Service):
        check_access_origin(request)
        return service.access.disable()

    @app.post(prefix + '/access/attempts')
    def access_attempt(body: AccessRequest, request: Request, service: Service):
        check_access_origin(request)
        return service.access.attempt(body.requestId, body.pin)

    @app.get(prefix + '/access/attempts')
    def access_attempts(service: Service, after_id: Cursor = 0, limit: Limit = 20):
        return service.access.attempts(after_id, limit)

    @app.get(prefix + '/access/attempts/{request_id}')
    def access_attempt_status(request_id: UUID, service: Service):
        return service.access.get_attempt(str(request_id))

    @app.get(prefix + '/access/export.csv')
    def access_export(service: Service):
        return StreamingResponse(service.access.export(), media_type='text/csv; charset=utf-8',
                                 headers={'Content-Disposition': 'attachment; filename="accesos.csv"'})

    @app.get(prefix + '/ml/status')
    def ml_status(service: Service):
        return service.access.monitoring.status()

    @app.get(prefix + '/ml/predictions')
    def ml_predictions(service: Service, after_id: Cursor = 0, limit: Limit = 20):
        return service.access.monitoring.predictions(after_id, limit)

    @app.get(prefix + "/health")
    def health(service: Service):
        storage = service.store.health()
        return JSONResponse(status_code=200 if storage["ok"] else 503,
                            content={"ok": storage["ok"], "service": "microp-backend", "protocolVersion": 2,
                                     "storage": storage, "boardsConnected": sum(item["connected"] for item in service.snapshots()),
                                     **service.connection_status()})

    @app.post(prefix + '/gateway/connect')
    def gateway_connect(body: ConnectionRequest, service: Service):
        return service.gateway_control('connect', body.port)

    @app.post(prefix + '/gateway/disconnect')
    def gateway_disconnect(service: Service):
        return service.gateway_control('disconnect')

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
        return service.control(origin, "connect", body.model_dump())

    @app.post(prefix + "/boards/{origin}/disconnect")
    def disconnect(origin: Origin, service: Service):
        return service.control(origin, "disconnect")

    @app.put(prefix + "/boards/{origin}/config")
    def configure(origin: Origin, body: BoardConfig, service: Service):
        return service.control(origin, "config", body.model_dump())

    @app.post(prefix + "/boards/{origin}/start")
    def start(origin: Origin, service: Service):
        return service.control(origin, "start")

    @app.post(prefix + "/boards/{origin}/stop")
    def stop(origin: Origin, service: Service):
        return service.control(origin, "stop")

    @app.put(prefix + "/boards/{origin}/sensors/{sensor}")
    def enable(origin: Origin, sensor: Sensor, body: EnableRequest, service: Service):
        return service.control(origin, "enable", {"sensor": sensor, "enabled": body.enabled})

    @app.get(prefix + '/scenarios')
    def scenarios(service: Service):
        return service.experiments.catalog()

    @app.get(prefix + '/sessions')
    def sessions(service: Service, after_id: Cursor = 0, limit: Limit = 20):
        return service.experiments.repository.sessions(after_id, limit)

    @app.post(prefix + '/sessions', status_code=201)
    def create_session(body: SessionRequest, service: Service):
        return service.experiments.create_session(body.model_dump())

    @app.get(prefix + '/sessions/{session_id}')
    def session(session_id: UUID, service: Service):
        return service.experiments.repository.session(str(session_id))

    @app.post(prefix + '/sessions/{session_id}/close')
    def close_session(session_id: UUID, service: Service):
        return service.experiments.close_session(str(session_id))

    @app.post(prefix + '/sessions/{session_id}/trials', status_code=201)
    def create_trial(session_id: UUID, body: TrialRequest, service: Service):
        return service.experiments.create_trial(str(session_id), body.scenario, body.notes)

    @app.get(prefix + '/trials')
    def trials(service: Service, session_id: UUID | None = None, after_id: Cursor = 0, limit: Limit = 20):
        if session_id:
            service.experiments.repository.session(str(session_id))
        return service.experiments.repository.trials(str(session_id) if session_id else None, after_id, limit)

    @app.get(prefix + '/trials/active')
    def active_trial(service: Service):
        return {'trial': service.experiments.active()}

    @app.get(prefix + '/trials/{trial_id}')
    def trial(trial_id: UUID, service: Service):
        return service.experiments.repository.trial(str(trial_id))

    @app.post(prefix + '/trials/{trial_id}/start')
    def start_trial(trial_id: UUID, service: Service):
        return service.experiments.start(str(trial_id))

    @app.post(prefix + '/trials/{trial_id}/stop')
    def stop_trial(trial_id: UUID, service: Service):
        return service.experiments.stop(str(trial_id))

    @app.post(prefix + '/trials/{trial_id}/review', status_code=202)
    def review_trial(trial_id: UUID, body: ReviewRequest, service: Service):
        return service.experiments.review(str(trial_id), body.confirmed, body.notes)

    @app.get(prefix + '/dataset/summary')
    def dataset_summary(service: Service):
        return service.experiments.repository.summary()

    @app.get(prefix + '/dataset/export.zip')
    def dataset_export(service: Service, session_id: Annotated[list[UUID], Query(min_length=1, max_length=100)]):
        temporary = export_dataset(service.store, service.experiments.repository, [str(item) for item in session_id])

        def chunks():
            try:
                while data := temporary.read(65536):
                    yield data
            finally:
                temporary.close()

        from starlette.background import BackgroundTask
        return StreamingResponse(chunks(), media_type='application/zip', background=BackgroundTask(temporary.close),
                                 headers={'Content-Disposition': 'attachment; filename="dataset-grupo-c.zip"'})

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

