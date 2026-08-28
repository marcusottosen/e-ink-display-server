"""Configuration for the fixed, outbound-only Raspberry Pi agent."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Read agent settings without ever serialising or logging the device token."""

    model_config = SettingsConfigDict(
        env_file="/etc/inky-agent/config.env",
        env_prefix="INKY_AGENT_",
        extra="ignore",
    )

    server_url: str = "http://127.0.0.1:8000"
    display_id: str = "inky-main"
    data_dir: Path = Path("/var/lib/inky-agent")
    device_token: SecretStr = SecretStr("")
    poll_interval_seconds: int = 30
    heartbeat_interval_seconds: int = 60
    request_timeout_seconds: float = 30
    retry_initial_seconds: float = 2
    retry_max_seconds: float = 60
    hardware_enabled: bool = True

    @model_validator(mode="after")
    def validate_settings(self) -> AgentSettings:
        parsed = urlsplit(self.server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("INKY_AGENT_SERVER_URL must be an http:// or https:// URL")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("INKY_AGENT_SERVER_URL must not include a path, query, or fragment")
        if not self.display_id:
            raise ValueError("INKY_AGENT_DISPLAY_ID must not be empty")
        if self.poll_interval_seconds < 5 or self.heartbeat_interval_seconds < 5:
            raise ValueError("poll and heartbeat intervals must be at least five seconds")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request timeout must be positive")
        if self.retry_initial_seconds <= 0 or self.retry_max_seconds < self.retry_initial_seconds:
            raise ValueError("retry intervals are invalid")
        return self

    @property
    def base_url(self) -> str:
        return self.server_url.rstrip("/")
