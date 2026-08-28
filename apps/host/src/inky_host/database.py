"""SQLite storage for the home display tool."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Engine, ForeignKey, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from inky_contract import RenderSettings

from .config import Settings


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class DisplayRecord(Base):
    __tablename__ = "displays"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    device_token_hash: Mapped[str] = mapped_column(String(64))
    orientation: Mapped[str] = mapped_column(String(16))
    rotation: Mapped[int] = mapped_column(Integer)
    time_zone: Mapped[str] = mapped_column(String(64))
    default_render_settings: Mapped[dict[str, object]] = mapped_column(JSON)
    current_revision: Mapped[int] = mapped_column(Integer, default=0)
    desired_revision: Mapped[int] = mapped_column(Integer, default=0)
    desired_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    desired_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConnectionSettingsRecord(Base):
    """Singleton configuration for how the fixed Pi reaches this host."""

    __tablename__ = "connection_settings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    advertised_host: Mapped[str] = mapped_column(String(255))
    advertised_port: Mapped[int] = mapped_column(Integer)
    agent_poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=30)
    agent_heartbeat_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    agent_auth_required: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AssetRecord(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(512), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    render_settings: Mapped[dict[str, object]] = mapped_column(
        JSON, default=lambda: RenderSettings().model_dump(mode="json")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    storage_path: Mapped[str] = mapped_column(String(512), unique=True)
    renderer_version: Mapped[str] = mapped_column(String(64))
    render_settings: Mapped[dict[str, object]] = mapped_column(JSON)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    palette: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DisplayJobRecord(Base):
    __tablename__ = "display_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_id: Mapped[str] = mapped_column(ForeignKey("displays.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    album_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    render_settings: Mapped[dict[str, object]] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlbumRecord(Base):
    __tablename__ = "albums"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_id: Mapped[str] = mapped_column(ForeignKey("displays.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    order_mode: Mapped[str] = mapped_column(String(16), default="sequential")
    interval_seconds: Mapped[int] = mapped_column(Integer, default=1_200)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_running: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    time_zone: Mapped[str] = mapped_column(String(64))
    schedule_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    default_render_settings: Mapped[dict[str, object]] = mapped_column(JSON)
    next_item_index: Mapped[int] = mapped_column(Integer, default=0)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AlbumItemRecord(Base):
    __tablename__ = "album_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    album_id: Mapped[str] = mapped_column(ForeignKey("albums.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ActivityRecord(Base):
    __tablename__ = "activity"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    display_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    album_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


def record_activity(
    session: Session,
    event_type: str,
    message: str,
    *,
    display_id: str | None = None,
    asset_id: str | None = None,
    album_id: str | None = None,
    job_id: str | None = None,
) -> ActivityRecord:
    record = ActivityRecord(
        id=str(uuid4()),
        event_type=event_type,
        message=message,
        display_id=display_id,
        asset_id=asset_id,
        album_id=album_id,
        job_id=job_id,
    )
    session.add(record)
    return record


def _apply_sqlite_migrations(engine: Engine) -> None:
    """Add columns needed when an existing SQLite file is opened by newer code."""

    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(assets)"))}
        if "deleted_at" not in columns:
            connection.execute(text("ALTER TABLE assets ADD COLUMN deleted_at DATETIME"))
        job_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(display_jobs)"))}
        if "album_id" not in job_columns:
            connection.execute(text("ALTER TABLE display_jobs ADD COLUMN album_id VARCHAR(36)"))
        if "render_settings" not in columns:
            connection.execute(text("ALTER TABLE assets ADD COLUMN render_settings JSON"))
        album_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(albums)"))}
        if "is_temporary" not in album_columns:
            connection.execute(text("ALTER TABLE albums ADD COLUMN is_temporary BOOLEAN NOT NULL DEFAULT 0"))


def create_session_factory(settings: Settings) -> sessionmaker[Session]:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {}
    engine = create_engine(settings.resolved_database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    _apply_sqlite_migrations(engine)
    return sessionmaker(engine, expire_on_commit=False)
