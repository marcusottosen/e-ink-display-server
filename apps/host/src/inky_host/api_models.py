"""Host-only HTTP response and settings models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from inky_contract import DisplayOrientation, DisplayRotation, RenderSettings


class AssetResponse(BaseModel):
    id: str
    original_filename: str
    sha256: str
    mime_type: str
    file_size: int
    width: int | None
    height: int | None
    created_at: datetime
    deleted_at: datetime | None
    preview_url: str | None = None


class JobResponse(BaseModel):
    id: str
    status: str
    revision: int | None
    asset_id: str
    artifact_sha256: str | None = None
    preview_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DisplaySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    orientation: DisplayOrientation | None = None
    rotation: DisplayRotation | None = None
    default_render_settings: RenderSettings | None = None


class DisplayResponse(BaseModel):
    id: str
    name: str
    width: int = 800
    height: int = 480
    orientation: DisplayOrientation
    rotation: DisplayRotation
    time_zone: str
    current_revision: int
    desired_revision: int
    desired_job_id: str | None
    last_seen_at: datetime | None
    last_error: str | None
    default_render_settings: RenderSettings


class ConnectionSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advertised_host: str = Field(min_length=10, max_length=255)
    advertised_port: int = Field(ge=1, le=65535)
    agent_poll_interval_seconds: int = Field(ge=5, le=3600)
    agent_heartbeat_interval_seconds: int = Field(ge=5, le=3600)
    agent_auth_required: bool = False

    @model_validator(mode="after")
    def validate_advertised_host(self) -> ConnectionSettingsUpdate:
        parsed = urlsplit(self.advertised_host)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("advertised_host must be an http:// or https:// host")
        if parsed.port is not None or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("advertised_host must not include a port, path, query, or fragment")
        return self


class ConnectionSettingsResponse(ConnectionSettingsUpdate):
    display_id: str
    server_url: str
    updated_at: datetime


class AlbumOrderMode(StrEnum):
    SEQUENTIAL = "sequential"
    SHUFFLE = "shuffle"


class AlbumItemInput(BaseModel):
    asset_id: UUID


class AlbumCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    display_id: str = "inky-main"
    asset_ids: list[UUID] = Field(min_length=1)
    order_mode: AlbumOrderMode = AlbumOrderMode.SEQUENTIAL
    interval_seconds: int = Field(default=120, ge=60, le=86_400)
    enabled: bool = True
    time_zone: str = Field(default="Europe/Copenhagen", min_length=1, max_length=64)
    schedule_start_at: datetime | None = None
    schedule_end_at: datetime | None = None
    default_render_settings: RenderSettings = RenderSettings()

    @model_validator(mode="after")
    def validate_schedule_window(self) -> AlbumCreate:
        if self.schedule_start_at and self.schedule_end_at and self.schedule_end_at <= self.schedule_start_at:
            raise ValueError("schedule_end_at must be after schedule_start_at")
        return self


class AlbumUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    order_mode: AlbumOrderMode | None = None
    interval_seconds: int | None = Field(default=None, ge=60, le=86_400)
    enabled: bool | None = None
    time_zone: str | None = Field(default=None, min_length=1, max_length=64)
    schedule_start_at: datetime | None = None
    schedule_end_at: datetime | None = None
    default_render_settings: RenderSettings | None = None

    @model_validator(mode="after")
    def validate_complete_schedule_window(self) -> AlbumUpdate:
        if self.schedule_start_at and self.schedule_end_at and self.schedule_end_at <= self.schedule_start_at:
            raise ValueError("schedule_end_at must be after schedule_start_at")
        return self


class AlbumItemsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ids: list[UUID] = Field(min_length=1)


class AlbumItemResponse(BaseModel):
    id: str
    asset_id: str
    position: int
    asset: AssetResponse


class AlbumResponse(BaseModel):
    id: str
    display_id: str
    name: str
    order_mode: AlbumOrderMode
    interval_seconds: int
    enabled: bool
    is_running: bool
    time_zone: str
    schedule_start_at: datetime | None
    schedule_end_at: datetime | None
    default_render_settings: RenderSettings
    next_item_index: int
    next_run_at: datetime | None
    items: list[AlbumItemResponse]
    created_at: datetime
    updated_at: datetime


class BulkDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ids: list[UUID] = Field(min_length=1, max_length=100)


class DeleteResult(BaseModel):
    deleted_ids: list[str]


class ActivityResponse(BaseModel):
    id: str
    event_type: str
    message: str
    display_id: str | None
    asset_id: str | None
    album_id: str | None
    job_id: str | None
    created_at: datetime
