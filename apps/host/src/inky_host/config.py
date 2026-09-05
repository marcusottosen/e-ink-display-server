"""Configuration for the Docker host."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from inky_contract import (
    DisplayOrientation,
    DisplayProfile,
    DisplayRotation,
    PaletteColor,
    RenderSettings,
)


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local `.env` file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="INKY_", extra="ignore")

    log_level: str = "INFO"
    data_dir: Path = Path("data")
    database_url: str | None = None
    max_upload_bytes: int = 20 * 1024 * 1024
    max_source_pixels: int = 40_000_000

    display_id: str = "inky-main"
    display_name: str = "Main Inky Display"
    display_orientation: DisplayOrientation = DisplayOrientation.LANDSCAPE
    display_rotation_degrees: DisplayRotation = DisplayRotation.DEGREES_0
    display_time_zone: str = "Europe/Copenhagen"
    agent_device_token: SecretStr = SecretStr("home-agent-token-change-me")
    agent_auth_required: bool = False

    @model_validator(mode="after")
    def validate_token_when_enabled(self) -> Settings:
        token = self.agent_device_token.get_secret_value()
        if self.agent_auth_required and token.startswith(("home-", "development-", "replace-")):
            raise ValueError("Set INKY_AGENT_DEVICE_TOKEN before enabling device-token checking")
        return self

    @cached_property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir.resolve() / 'inky.sqlite3'}"

    def initial_display_profile(self) -> DisplayProfile:
        return DisplayProfile(
            id=self.display_id,
            name=self.display_name,
            width=800,
            height=480,
            palette=tuple(PaletteColor),
            orientation=self.display_orientation,
            rotation=self.display_rotation_degrees,
            default_render_settings=RenderSettings(),
            time_zone=self.display_time_zone,
        )
