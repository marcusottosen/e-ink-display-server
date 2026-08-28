"""Pydantic models for the Inky Display System v1 contract."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

API_VERSION = "v1"
SHA256_HEX_LENGTH = 64

Sha256 = Annotated[str, Field(pattern=rf"^[a-f0-9]{{{SHA256_HEX_LENGTH}}}$")]


class PaletteColor(StrEnum):
    """The seven target display colours, including the uninked white panel state."""

    BLACK = "black"
    WHITE = "white"
    RED = "red"
    YELLOW = "yellow"
    BLUE = "blue"
    GREEN = "green"
    ORANGE = "orange"


class DisplayOrientation(StrEnum):
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"


class DisplayRotation(IntEnum):
    DEGREES_0 = 0
    DEGREES_90 = 90
    DEGREES_180 = 180
    DEGREES_270 = 270


class FitMode(StrEnum):
    CROP = "crop"
    CONTAIN = "contain"
    STRETCH = "stretch"


class DitherMode(StrEnum):
    NONE = "none"
    FLOYD_STEINBERG = "floyd-steinberg"


class ArtifactFormat(StrEnum):
    RGB_PNG = "rgb-png"


class JobEvent(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class RenderSettings(BaseModel):
    """Content treatment only; it does not change physical display orientation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fit_mode: FitMode = FitMode.CROP
    # Kept only so existing saved render settings remain readable. The host no
    # longer performs palette conversion or dithering, so this has no effect.
    dither_mode: DitherMode = DitherMode.NONE
    content_rotation: DisplayRotation = DisplayRotation.DEGREES_0
    focal_point_x: Annotated[float, Field(ge=0, le=1)] = 0.5
    focal_point_y: Annotated[float, Field(ge=0, le=1)] = 0.5
    flip_horizontal: bool = False
    flip_vertical: bool = False


class DisplayProfile(BaseModel):
    """Fixed server-owned properties of a configured display target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")]
    name: Annotated[str, Field(min_length=1, max_length=120)]
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    palette: Annotated[tuple[PaletteColor, ...], Field(min_length=7, max_length=7)]
    orientation: DisplayOrientation
    rotation: DisplayRotation
    default_render_settings: RenderSettings
    time_zone: Annotated[str, Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def has_exactly_the_supported_palette(self) -> DisplayProfile:
        if set(self.palette) != set(PaletteColor):
            msg = "palette must contain each supported display colour exactly once"
            raise ValueError(msg)
        return self


class ArtifactDescriptor(BaseModel):
    """Metadata required to safely retrieve and verify an immutable artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sha256: Sha256
    url: Annotated[str, Field(pattern=r"^/api/v1/artifacts/[a-f0-9]{64}$")]
    format: ArtifactFormat
    media_type: str = "image/png"
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    palette: Annotated[tuple[PaletteColor, ...], Field(min_length=7, max_length=7)]
    renderer_version: Annotated[str, Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def url_matches_checksum(self) -> ArtifactDescriptor:
        if self.url != f"/api/v1/artifacts/{self.sha256}":
            msg = "url must point to the artifact's SHA-256 checksum"
            raise ValueError(msg)
        return self


class DesiredState(BaseModel):
    """Latest desired state; old revisions are intentionally not queued to the Pi."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_version: Literal["v1"] = "v1"
    display_id: str
    revision: Annotated[int, Field(ge=1)]
    job_id: UUID
    artifact: ArtifactDescriptor
    not_before: datetime | None = None
    expires_at: datetime | None = None


class AgentHeartbeat(BaseModel):
    """Liveness report from a known agent, not a display capability registration."""

    model_config = ConfigDict(extra="forbid")

    current_revision: Annotated[int, Field(ge=0)]
    last_successful_artifact_sha256: Sha256 | None = None
    sent_at: datetime


class JobAcknowledgement(BaseModel):
    """At-least-once job lifecycle report from the Pi."""

    model_config = ConfigDict(extra="forbid")

    event: JobEvent
    completed_revision: Annotated[int, Field(ge=1)] | None = None
    error_code: Annotated[str, Field(max_length=64)] | None = None
    error_message: Annotated[str, Field(max_length=1000)] | None = None
    occurred_at: datetime


class DisplayNowRequest(BaseModel):
    """Host UI request to render an existing asset and make it desired immediately."""

    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    render_settings: RenderSettings | None = None
