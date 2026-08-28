"""Host-only HTTP response and settings models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from inky_contract import DisplayOrientation, DisplayRotation, RenderSettings


class AssetResponse(BaseModel):
    id: str
    original_filename: str
    sha256: str
    mime_type: str
    file_size: int
    created_at: datetime
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
