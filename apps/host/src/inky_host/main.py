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

from .albums import AlbumScheduler, album_response
from .api_models import (
    ActivityResponse,
    AlbumCreate,
    AlbumItemsUpdate,
    AlbumResponse,
    AlbumUpdate,
    AssetResponse,
    BulkDeleteRequest,
    ConnectionSettingsResponse,
    ConnectionSettingsUpdate,
    DeleteResult,
    DisplayResponse,
    DisplaySettingsUpdate,
    JobResponse,
)
from .config import Settings
from .database import (
    ActivityRecord,
    AlbumItemRecord,
    AlbumRecord,
    ArtifactRecord,
    AssetRecord,
    ConnectionSettingsRecord,
    DisplayJobRecord,
    DisplayRecord,
    create_session_factory,
    record_activity,
    utc_now,
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
        width=asset.width,
        height=asset.height,
        created_at=asset.created_at,
        deleted_at=asset.deleted_at,
        preview_url=preview_url,
    )


def _soft_delete_assets(asset_ids: list[str], request: Request) -> DeleteResult:
    sessions: sessionmaker[Session] = request.app.state.sessions
    with sessions() as session:
        assets = {asset_id: session.get(AssetRecord, asset_id) for asset_id in asset_ids}
        missing = [asset_id for asset_id, asset in assets.items() if asset is None]
        if missing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more assets were not found")
        deleted_ids: list[str] = []
        for asset_id, asset in assets.items():
            if asset is None or asset.deleted_at is not None:
                continue
            asset.deleted_at = utc_now()
            deleted_ids.append(asset_id)
            record_activity(
                session,
                "asset.deleted",
                f"Moved '{asset.original_filename}' to the trash",
                asset_id=asset.id,
            )
        session.commit()
        return DeleteResult(deleted_ids=deleted_ids)


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


def _seed_connection_settings(sessions: sessionmaker[Session], settings: Settings) -> None:
    with sessions() as session:
        if session.get(ConnectionSettingsRecord, "default") is not None:
            return
        session.add(
            ConnectionSettingsRecord(
                id="default",
                advertised_host=settings.advertised_host.rstrip("/"),
                advertised_port=settings.advertised_port,
                agent_poll_interval_seconds=settings.agent_poll_interval_seconds,
                agent_heartbeat_interval_seconds=settings.agent_heartbeat_interval_seconds,
                agent_auth_required=settings.agent_auth_required,
            )
        )
        session.commit()


def _connection_settings_response(
    connection: ConnectionSettingsRecord, display_id: str
) -> ConnectionSettingsResponse:
    return ConnectionSettingsResponse(
        display_id=display_id,
        advertised_host=connection.advertised_host,
        advertised_port=connection.advertised_port,
        server_url=f"{connection.advertised_host.rstrip('/')}:{connection.advertised_port}",
        agent_poll_interval_seconds=connection.agent_poll_interval_seconds,
        agent_heartbeat_interval_seconds=connection.agent_heartbeat_interval_seconds,
        agent_auth_required=connection.agent_auth_required,
        updated_at=connection.updated_at,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or Settings()
    configure_logging(runtime_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        sessions = create_session_factory(runtime_settings)
        storage = Storage(runtime_settings.data_dir)
        _seed_display(sessions, runtime_settings)
        _seed_connection_settings(sessions, runtime_settings)
        worker = RenderWorker(sessions, storage, runtime_settings.max_source_pixels)
        album_scheduler = AlbumScheduler(sessions, worker)
        app.state.settings = runtime_settings
        app.state.sessions = sessions
        app.state.storage = storage
        app.state.worker = worker
        app.state.album_scheduler = album_scheduler
        await worker.start()
        await album_scheduler.start()
        logger.info("host started", extra={"display_id": runtime_settings.display_id})
        try:
            yield
        finally:
            await album_scheduler.stop()
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
            connection = session.get(ConnectionSettingsRecord, "default")
            auth_required = (
                connection.agent_auth_required if connection is not None else runtime_settings.agent_auth_required
            )
            if display is None or (
                auth_required and (not token or not hmac.compare_digest(display.device_token_hash, _token_hash(token)))
            ):
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

    @app.get("/api/v1/settings/connection", response_model=ConnectionSettingsResponse)
    def get_connection_settings(request: Request) -> ConnectionSettingsResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            connection = session.get(ConnectionSettingsRecord, "default")
            if connection is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Connection settings unavailable",
                )
            return _connection_settings_response(connection, request.app.state.settings.display_id)

    @app.patch("/api/v1/settings/connection", response_model=ConnectionSettingsResponse)
    def update_connection_settings(
        update: ConnectionSettingsUpdate, request: Request
    ) -> ConnectionSettingsResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            connection = session.get(ConnectionSettingsRecord, "default")
            if connection is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Connection settings unavailable",
                )
            connection.advertised_host = update.advertised_host.rstrip("/")
            connection.advertised_port = update.advertised_port
            connection.agent_poll_interval_seconds = update.agent_poll_interval_seconds
            connection.agent_heartbeat_interval_seconds = update.agent_heartbeat_interval_seconds
            connection.agent_auth_required = update.agent_auth_required
            record_activity(
                session,
                "connection.settings-updated",
                "Updated the Pi-to-host connection settings",
                display_id=request.app.state.settings.display_id,
            )
            session.commit()
            session.refresh(connection)
            return _connection_settings_response(connection, request.app.state.settings.display_id)

    @app.post("/api/v1/assets", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
    async def upload_asset(
        request: Request,
        file: UploadFile = File(...),
    ) -> AssetResponse:
        storage: Storage = request.app.state.storage
        runtime: Settings = request.app.state.settings
        stored = await storage.save_upload(file, runtime.max_upload_bytes)
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            asset = session.scalar(select(AssetRecord).where(AssetRecord.sha256 == stored.sha256))
            if asset is None:
                asset = AssetRecord(
                    id=str(uuid4()),
                    original_filename=stored.filename,
                    sha256=stored.sha256,
                    storage_path=stored.relative_path,
                    mime_type=stored.mime_type,
                    file_size=stored.file_size,
                )
                session.add(asset)
                record_activity(
                    session,
                    "asset.uploaded",
                    f"Uploaded '{asset.original_filename}'",
                    asset_id=asset.id,
                )
            elif asset.deleted_at is not None:
                asset.deleted_at = None
                record_activity(
                    session,
                    "asset.restored-by-upload",
                    f"Restored '{asset.original_filename}' from a matching upload",
                    asset_id=asset.id,
                )
            session.commit()
            session.refresh(asset)
            response = _asset_response(asset)
        logger.info("asset uploaded", extra={"asset_id": asset.id, "sha256": stored.sha256})
        return response

    @app.get("/api/v1/assets", response_model=list[AssetResponse])
    def list_assets(request: Request, include_deleted: bool = False) -> list[AssetResponse]:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            query = select(AssetRecord).order_by(desc(AssetRecord.created_at))
            if not include_deleted:
                query = query.where(AssetRecord.deleted_at.is_(None))
            assets = session.scalars(query).all()
            return [
                _asset_response(asset, f"/api/v1/assets/{asset.id}/preview" if asset.width is not None else None)
                for asset in assets
            ]

    @app.delete("/api/v1/assets/{asset_id}", response_model=DeleteResult)
    def delete_asset(asset_id: str, request: Request) -> DeleteResult:
        return _soft_delete_assets([asset_id], request)

    @app.post("/api/v1/assets/bulk-delete", response_model=DeleteResult)
    def bulk_delete_assets(body: BulkDeleteRequest, request: Request) -> DeleteResult:
        return _soft_delete_assets([str(asset_id) for asset_id in body.asset_ids], request)

    @app.post("/api/v1/assets/{asset_id}/restore", response_model=AssetResponse)
    def restore_asset(asset_id: str, request: Request) -> AssetResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            asset = session.get(AssetRecord, asset_id)
            if asset is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
            asset.deleted_at = None
            record_activity(session, "asset.restored", f"Restored '{asset.original_filename}'", asset_id=asset.id)
            session.commit()
            return _asset_response(asset, f"/api/v1/assets/{asset.id}/preview")

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
            record_activity(
                session,
                "display.settings-updated",
                f"Updated settings for display '{display.name}'",
                display_id=display.id,
            )
            session.commit()
            session.refresh(display)
            return _display_response(display)

    @app.get("/api/v1/activity", response_model=list[ActivityResponse])
    def list_activity(request: Request, limit: int = 50) -> list[ActivityResponse]:
        safe_limit = min(max(limit, 1), 200)
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            events = session.scalars(
                select(ActivityRecord).order_by(desc(ActivityRecord.created_at)).limit(safe_limit)
            ).all()
            return [
                ActivityResponse(
                    id=event.id,
                    event_type=event.event_type,
                    message=event.message,
                    display_id=event.display_id,
                    asset_id=event.asset_id,
                    album_id=event.album_id,
                    job_id=event.job_id,
                    created_at=event.created_at,
                )
                for event in events
            ]

    @app.get("/api/v1/albums", response_model=list[AlbumResponse])
    def list_albums(request: Request) -> list[AlbumResponse]:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            albums = session.scalars(select(AlbumRecord).order_by(AlbumRecord.created_at.desc())).all()
            return [album_response(session, album) for album in albums]

    @app.post("/api/v1/albums", response_model=AlbumResponse, status_code=status.HTTP_201_CREATED)
    def create_album(body: AlbumCreate, request: Request) -> AlbumResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            if session.get(DisplayRecord, body.display_id) is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Display not found")
            if session.scalar(select(AlbumRecord).where(AlbumRecord.name == body.name)) is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Album name already exists")
            assets = [session.get(AssetRecord, str(asset_id)) for asset_id in body.asset_ids]
            available_assets = [asset for asset in assets if asset is not None and asset.deleted_at is None]
            if len(available_assets) != len(assets):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Albums require available gallery images"
                )
            album = AlbumRecord(
                id=str(uuid4()),
                display_id=body.display_id,
                name=body.name,
                order_mode=body.order_mode.value,
                interval_seconds=body.interval_seconds,
                enabled=body.enabled,
                time_zone=body.time_zone,
                schedule_start_at=body.schedule_start_at,
                schedule_end_at=body.schedule_end_at,
                default_render_settings=body.default_render_settings.model_dump(mode="json"),
            )
            session.add(album)
            session.flush()
            for position, asset in enumerate(available_assets):
                session.add(AlbumItemRecord(id=str(uuid4()), album_id=album.id, asset_id=asset.id, position=position))
            record_activity(
                session,
                "album.created",
                f"Created album '{album.name}'",
                display_id=album.display_id,
                album_id=album.id,
            )
            session.commit()
            return album_response(session, album)

    @app.get("/api/v1/albums/{album_id}", response_model=AlbumResponse)
    def get_album(album_id: str, request: Request) -> AlbumResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            album = session.get(AlbumRecord, album_id)
            if album is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found")
            return album_response(session, album)

    @app.patch("/api/v1/albums/{album_id}", response_model=AlbumResponse)
    def update_album(album_id: str, body: AlbumUpdate, request: Request) -> AlbumResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            album = session.get(AlbumRecord, album_id)
            if album is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found")
            values = body.model_dump(exclude_unset=True)
            for field, value in values.items():
                if field == "order_mode":
                    value = value.value
                if field == "default_render_settings":
                    value = value.model_dump(mode="json")
                setattr(album, field, value)
            if album.schedule_start_at and album.schedule_end_at and album.schedule_end_at <= album.schedule_start_at:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="schedule_end_at must be after schedule_start_at",
                )
            record_activity(
                session,
                "album.updated",
                f"Updated album '{album.name}'",
                display_id=album.display_id,
                album_id=album.id,
            )
            session.commit()
            return album_response(session, album)

    @app.put("/api/v1/albums/{album_id}/items", response_model=AlbumResponse)
    def replace_album_items(album_id: str, body: AlbumItemsUpdate, request: Request) -> AlbumResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            album = session.get(AlbumRecord, album_id)
            if album is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found")
            assets = [session.get(AssetRecord, str(asset_id)) for asset_id in body.asset_ids]
            available_assets = [asset for asset in assets if asset is not None and asset.deleted_at is None]
            if len(available_assets) != len(assets):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Albums require available gallery images"
                )
            existing_items = session.scalars(select(AlbumItemRecord).where(AlbumItemRecord.album_id == album.id)).all()
            for item in existing_items:
                session.delete(item)
            for position, asset in enumerate(available_assets):
                session.add(AlbumItemRecord(id=str(uuid4()), album_id=album.id, asset_id=asset.id, position=position))
            album.next_item_index = 0
            record_activity(
                session,
                "album.items-updated",
                f"Updated items in album '{album.name}'",
                display_id=album.display_id,
                album_id=album.id,
            )
            session.commit()
            return album_response(session, album)

    @app.post("/api/v1/albums/{album_id}/run", response_model=AlbumResponse)
    async def run_album(album_id: str, request: Request) -> AlbumResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            album = session.get(AlbumRecord, album_id)
            if album is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found")
            if not session.scalar(select(AlbumItemRecord.id).where(AlbumItemRecord.album_id == album_id)):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Album has no images")
        await request.app.state.album_scheduler.run_album(album_id)
        with sessions() as session:
            album = session.get(AlbumRecord, album_id)
            if album is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found")
            if not album.is_running:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Album has no available images")
            return album_response(session, album)

    @app.post("/api/v1/albums/{album_id}/stop", response_model=AlbumResponse)
    async def stop_album(album_id: str, request: Request) -> AlbumResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            if session.get(AlbumRecord, album_id) is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found")
        await request.app.state.album_scheduler.stop_album(album_id)
        with sessions() as session:
            album = session.get(AlbumRecord, album_id)
            if album is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found")
            return album_response(session, album)

    @app.delete("/api/v1/albums/{album_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_album(album_id: str, request: Request) -> Response:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            album = session.get(AlbumRecord, album_id)
            if album is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found")
            if album.is_running:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stop the album before deleting it")
            for item in session.scalars(select(AlbumItemRecord).where(AlbumItemRecord.album_id == album.id)):
                session.delete(item)
            record_activity(
                session,
                "album.deleted",
                f"Deleted album '{album.name}'",
                display_id=album.display_id,
                album_id=album.id,
            )
            session.delete(album)
            session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/v1/displays/{display_id}/display-now", response_model=JobResponse)
    async def display_now(display_id: str, body: DisplayNowRequest, request: Request) -> JobResponse:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions() as session:
            display = session.get(DisplayRecord, display_id)
            asset = session.get(AssetRecord, str(body.asset_id))
            if display is None or asset is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Display or asset not found")
            if asset.deleted_at is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Asset is in the trash")
            render_settings = body.render_settings or RenderSettings.model_validate(display.default_render_settings)
            job = create_display_now_job(session, display, asset, render_settings)
            record_activity(
                session,
                "display-now.queued",
                f"Queued '{asset.original_filename}' for immediate display",
                display_id=display.id,
                asset_id=asset.id,
                job_id=job.id,
            )
            session.commit()
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
                    format=ArtifactFormat.RGB_PNG,
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
            record_activity(
                session,
                f"job.{event.value}",
                f"Display job {job.id} reported {event.value}",
                display_id=display_id,
                asset_id=job.asset_id,
                job_id=job.id,
            )
            session.commit()
        return {"ok": True}

    return app


app = create_app()
