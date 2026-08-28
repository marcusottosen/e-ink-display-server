"""HTTP client for the Pi-pull host API."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from inky_contract import AgentHeartbeat, ArtifactDescriptor, DesiredState, JobAcknowledgement, JobEvent

from .config import AgentSettings
from .spool import AgentSpool


class HostClient:
    """Only makes outbound requests from the Pi to the already-known host."""

    def __init__(self, settings: AgentSettings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    def desired_state(self, current_revision: int) -> DesiredState | None:
        response = self._client.get(
            self._url(f"/api/v1/displays/{self._settings.display_id}/desired"),
            params={"current_revision": current_revision},
            headers=self._headers(),
        )
        if response.status_code == httpx.codes.NO_CONTENT:
            return None
        response.raise_for_status()
        return DesiredState.model_validate(response.json())

    def download_artifact(self, descriptor: ArtifactDescriptor, spool: AgentSpool) -> Path:
        with self._client.stream("GET", self._url(descriptor.url), headers=self._headers()) as response:
            response.raise_for_status()
            return spool.install_download(descriptor, response.iter_bytes())

    def heartbeat(self, current_revision: int, artifact_sha256: str | None) -> None:
        body = AgentHeartbeat(
            current_revision=current_revision,
            last_successful_artifact_sha256=artifact_sha256,
            sent_at=datetime.now(UTC),
        )
        response = self._client.post(
            self._url(f"/api/v1/displays/{self._settings.display_id}/heartbeat"),
            headers=self._headers(),
            json=body.model_dump(mode="json"),
        )
        response.raise_for_status()

    def acknowledge(
        self,
        job_id: str,
        event: JobEvent,
        *,
        revision: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        body = JobAcknowledgement(
            event=event,
            completed_revision=revision if event is JobEvent.COMPLETED else None,
            error_code=error_code,
            error_message=error_message,
            occurred_at=datetime.now(UTC),
        )
        response = self._client.post(
            self._url(f"/api/v1/displays/{self._settings.display_id}/jobs/{job_id}/{event.value}"),
            headers=self._headers(),
            json=body.model_dump(mode="json"),
        )
        response.raise_for_status()

    def _headers(self) -> dict[str, str]:
        token = self._settings.device_token.get_secret_value()
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _url(self, path: str) -> str:
        return f"{self._settings.base_url}{path}"
