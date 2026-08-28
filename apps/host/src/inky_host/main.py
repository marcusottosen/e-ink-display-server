"""FastAPI application for the single-display host vertical slice."""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.base import RequestResponseEndpoint

from inky_contract import (
    AgentHeartbeat,
    ArtifactDescriptor,
    ArtifactFormat,
    DesiredState,
    DisplayNowRequest,
    DisplayOrientation,
    DisplayRotation,
    JobAcknowledgement,
    JobEvent,
    RenderSettings,
)

from .api_models import AssetResponse, DisplayResponse, DisplaySettingsUpdate, JobResponse
from .config import Settings
from .database import (
    ArtifactRecord,
    AssetRecord,
    DisplayJobRecord,
    DisplayRecord,
    create_session_factory,
)
from .observability import configure_logging, request_id_context
from .profiles import profile_from_record
from .storage import Storage
from .worker import JobStatus, RenderWorker, create_display_now_job

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _asset_response(asset: AssetRecord, preview_url: str | None = None) -> AssetResponse:
    return AssetResponse(
        id=asset.id,
        original_filename=asset.original_filename,
        sha256=asset.sha256,
        mime_type=asset.mime_type,
        file_size=asset.file_size,
        created_at=asset.created_at,
        preview_url=preview_url,
    )


def _job_response(session: Session, job: DisplayJobRecord) -> JobResponse:
    artifact = session.get(ArtifactRecord, job.artifact_id) if job.artifact_id else None
    return JobResponse(
        id=job.id,
        status=job.status,
        revision=job.revision,
        asset_id=job.asset_id,
        artifact_sha256=artifact.sha256 if artifact else None,
        preview_url=f"/api/v1/jobs/{job.id}/preview" if artifact else None,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _display_response(display: DisplayRecord) -> DisplayResponse:
    return DisplayResponse(
        id=display.id,
        name=display.name,
        orientation=DisplayOrientation(display.orientation),
        rotation=DisplayRotation(display.rotation),
        time_zone=display.time_zone,
        current_revision=display.current_revision,
        desired_revision=display.desired_revision,
        desired_job_id=display.desired_job_id,
        last_seen_at=display.last_seen_at,
        last_error=display.last_error,
        default_render_settings=RenderSettings.model_validate(display.default_render_settings),
    )


def _seed_display(sessions: sessionmaker[Session], settings: Settings) -> None:
    profile = settings.initial_display_profile()
    with sessions() as session:
        if session.get(DisplayRecord, profile.id) is not None:
            return
        session.add(
            DisplayRecord(
                id=profile.id,
                name=profile.name,
                device_token_hash=_token_hash(settings.agent_device_token.get_secret_value()),
                orientation=profile.orientation.value,
                rotation=int(profile.rotation),
                time_zone=profile.time_zone,
                default_render_settings=profile.default_render_settings.model_dump(mode="json"),
            )
        )
        session.commit()


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or Settings()
    configure_logging(runtime_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        sessions = create_session_factory(runtime_settings)
        storage = Storage(runtime_settings.data_dir)
        _seed_display(sessions, runtime_settings)
        worker = RenderWorker(sessions, storage, runtime_settings.max_source_pixels)
        app.state.settings = runtime_settings
        app.state.sessions = sessions
        app.state.storage = storage
        app.state.worker = worker
        await worker.start()
        logger.info("host started", extra={"display_id": runtime_settings.display_id})
        try:
            yield
        finally:
            await worker.stop()
            logger.info("host stopped")

    app = FastAPI(title="Inky Display Host", version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def add_correlation_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = request.headers.get("X-Request-ID", str(uuid4()))
        token = request_id_context.set(correlation_id)
        try:
            response = await call_next(request)
        finally:
            request_id_context.reset(token)
        response.headers["X-Request-ID"] = correlation_id
        return response

    def get_sessions(request: Request) -> sessionmaker[Session]:
        return request.app.state.sessions  # type: ignore[no-any-return]

    def require_agent(request: Request, sessions: sessionmaker[Session] = Depends(get_sessions)) -> DisplayRecord:
        display_id = request.path_params.get("display_id", request.app.state.settings.display_id)
        authorization = request.headers.get("Authorization", "")
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        with sessions() as session:
            display = session.get(DisplayRecord, display_id)
            if display is None or not token or not hmac.compare_digest(display.device_token_hash, _token_hash(token)):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device token")
            session.expunge(display)
            return display

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health(request: Request) -> dict[str, str]:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok", "worker": "running"}

    @app.post("/api/v1/assets", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
    async def upload_asset(
        request: Request,
        file: UploadFile = File(...),
    ) -> AssetResponse:
        storage: Storage = request.app.state.storage
        runtime: Settings = request.app.state.settings
        stored = await storage.save_upload(file, runtime.max_upload_bytes)
        sessions: sessionmaker[Session] = request.app.state.sessions
        asset = AssetRecord(
            id=str(uuid4()),
            original_filename=stored.filename,
            sha256=stored.sha256,
            storage_path=stored.relative_path,
            mime_type=stored.mime_type,
            file_size=stored.file_size,
        )
        with sessions() as session:
            session.add(asset)
            session.commit()
            session.refresh(asset)
            response = _asset_response(asset)
        logger.info("asset uploaded", extra={"asset_id": asset.id, "sha256": stored.sha256})
        return response

    @app.get("/api/v1/assets", response_model=list[AssetResponse])
    def list_assets(request: Request) -> list[AssetResponse]:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            assets = session.scalars(select(AssetRecord).order_by(desc(AssetRecord.created_at))).all()
            return [_asset_response(asset, f"/api/v1/assets/{asset.id}/preview") for asset in assets]

    @app.get("/api/v1/assets/{asset_id}/preview")
    def asset_preview(asset_id: str, request: Request) -> FileResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        storage: Storage = request.app.state.storage
        with sessions() as session:
            artifact = session.scalar(
                select(ArtifactRecord)
                .where(ArtifactRecord.asset_id == asset_id)
                .order_by(desc(ArtifactRecord.created_at))
            )
            if artifact is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No rendered preview exists")
            path = storage.preview_path(artifact.sha256)
        return FileResponse(path, media_type="image/png")

    @app.get("/api/v1/displays/{display_id}", response_model=DisplayResponse)
    def get_display(display_id: str, request: Request) -> DisplayResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            display = session.get(DisplayRecord, display_id)
            if display is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Display not found")
            return _display_response(display)

    @app.patch("/api/v1/displays/{display_id}/settings", response_model=DisplayResponse)
    def update_display_settings(display_id: str, update: DisplaySettingsUpdate, request: Request) -> DisplayResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            display = session.get(DisplayRecord, display_id)
            if display is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Display not found")
            if update.name is not None:
                display.name = update.name
            if update.orientation is not None:
                display.orientation = update.orientation.value
            if update.rotation is not None:
                display.rotation = int(update.rotation)
            if update.default_render_settings is not None:
                display.default_render_settings = update.default_render_settings.model_dump(mode="json")
            session.commit()
            session.refresh(display)
            return _display_response(display)

    @app.post("/api/v1/displays/{display_id}/display-now", response_model=JobResponse)
    async def display_now(display_id: str, body: DisplayNowRequest, request: Request) -> JobResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            display = session.get(DisplayRecord, display_id)
            asset = session.get(AssetRecord, str(body.asset_id))
            if display is None or asset is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Display or asset not found")
            render_settings = body.render_settings or RenderSettings.model_validate(display.default_render_settings)
            job = create_display_now_job(session, display, asset, render_settings)
            response = _job_response(session, job)
        await request.app.state.worker.enqueue(job.id)
        logger.info("display-now queued", extra={"job_id": job.id, "asset_id": asset.id})
        return response

    @app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str, request: Request) -> JobResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            job = session.get(DisplayJobRecord, job_id)
            if job is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
            return _job_response(session, job)

    @app.get("/api/v1/jobs/{job_id}/preview")
    def job_preview(job_id: str, request: Request) -> FileResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        storage: Storage = request.app.state.storage
        with sessions() as session:
            job = session.get(DisplayJobRecord, job_id)
            artifact = session.get(ArtifactRecord, job.artifact_id) if job and job.artifact_id else None
            if artifact is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview is not ready")
            path = storage.preview_path(artifact.sha256)
        return FileResponse(path, media_type="image/png")

    @app.get("/api/v1/displays/{display_id}/desired", response_model=DesiredState)
    def desired_state(
        display_id: str,
        request: Request,
        current_revision: int = 0,
        _: DisplayRecord = Depends(require_agent),
    ) -> DesiredState | Response:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            display = session.get(DisplayRecord, display_id)
            if display is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Display not found")
            job = session.get(DisplayJobRecord, display.desired_job_id) if display and display.desired_job_id else None
            artifact = session.get(ArtifactRecord, job.artifact_id) if job and job.artifact_id else None
            if job is None or artifact is None or job.revision is None or job.revision <= current_revision:
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            return DesiredState(
                display_id=display_id,
                revision=job.revision,
                job_id=UUID(job.id),
                artifact=ArtifactDescriptor(
                    sha256=artifact.sha256,
                    url=f"/api/v1/artifacts/{artifact.sha256}",
                    format=ArtifactFormat.PALETTED_PNG,
                    width=artifact.width,
                    height=artifact.height,
                    palette=tuple(profile_from_record(display).palette),
                    renderer_version=artifact.renderer_version,
                ),
            )

    @app.get("/api/v1/artifacts/{sha256}")
    def download_artifact(sha256: str, request: Request, _: DisplayRecord = Depends(require_agent)) -> FileResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        storage: Storage = request.app.state.storage
        with sessions() as session:
            artifact = session.scalar(select(ArtifactRecord).where(ArtifactRecord.sha256 == sha256))
            if artifact is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
            path = storage.path(artifact.storage_path)
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, immutable"})

    @app.post("/api/v1/displays/{display_id}/heartbeat")
    def heartbeat(
        display_id: str,
        body: AgentHeartbeat,
        request: Request,
        _: DisplayRecord = Depends(require_agent),
    ) -> dict[str, bool]:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            display = session.get(DisplayRecord, display_id)
            if display is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Display not found")
            display.last_seen_at = body.sent_at
            session.commit()
        return {"ok": True}

    @app.post("/api/v1/displays/{display_id}/jobs/{job_id}/{event}")
    def acknowledge_job(
        display_id: str,
        job_id: str,
        event: JobEvent,
        body: JobAcknowledgement,
        request: Request,
        _: DisplayRecord = Depends(require_agent),
    ) -> dict[str, bool]:
        if body.event is not event:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Event does not match route")
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            display = session.get(DisplayRecord, display_id)
            job = session.get(DisplayJobRecord, job_id)
            if display is None or job is None or job.display_id != display_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Display job not found")
            display.last_seen_at = body.occurred_at
            if event is JobEvent.STARTED:
                job.status = JobStatus.STARTED
                job.started_at = body.occurred_at
            elif event is JobEvent.COMPLETED:
                job.status = JobStatus.COMPLETED
                job.completed_at = body.occurred_at
                if job.revision is not None:
                    display.current_revision = max(display.current_revision, job.revision)
                display.last_error = None
            else:
                job.status = JobStatus.FAILED
                job.failed_at = body.occurred_at
                job.error_code = body.error_code or "agent-failed"
                job.error_message = body.error_message or "The agent reported a display failure"
                display.last_error = job.error_message
            session.commit()
        return {"ok": True}

    return app


app = create_app()
