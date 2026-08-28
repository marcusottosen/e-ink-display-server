"""Resilient fixed-display Pi agent orchestration."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from inky_contract import ArtifactDescriptor, DesiredState, JobEvent

from .config import AgentSettings
from .hardware import SerializedDisplayWorker
from .spool import AgentSpool, AgentState, PendingAcknowledgement

logger = logging.getLogger(__name__)


class AgentTransport(Protocol):
    def desired_state(self, current_revision: int) -> DesiredState | None: ...

    def download_artifact(self, descriptor: ArtifactDescriptor, spool: AgentSpool) -> Path: ...

    def heartbeat(self, current_revision: int, artifact_sha256: str | None) -> None: ...

    def acknowledge(
        self,
        job_id: str,
        event: JobEvent,
        *,
        revision: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None: ...


class InkyAgent:
    def __init__(
        self,
        settings: AgentSettings,
        transport: AgentTransport,
        spool: AgentSpool,
        display_worker: SerializedDisplayWorker,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.spool = spool
        self.display_worker = display_worker
        self.state = spool.load_state()

    def run_once(self) -> bool:
        """Reconcile the latest desired revision once; return whether it refreshed."""

        self._flush_pending_acknowledgement()
        now = datetime.now(UTC)
        if self.state.heartbeat_is_due(now, self.settings.heartbeat_interval_seconds):
            self.transport.heartbeat(self.state.current_revision, self.state.last_successful_artifact_sha256)
            self.state = AgentState(
                current_revision=self.state.current_revision,
                last_successful_artifact_sha256=self.state.last_successful_artifact_sha256,
                last_heartbeat_at=now.isoformat(),
                pending_acknowledgement=self.state.pending_acknowledgement,
            )
            self.spool.save_state(self.state)

        desired = self.transport.desired_state(self.state.current_revision)
        if desired is None:
            return False
        return self._apply_desired_state(desired)

    def _apply_desired_state(self, desired: DesiredState) -> bool:
        artifact_path = self.transport.download_artifact(desired.artifact, self.spool)
        self.transport.acknowledge(str(desired.job_id), JobEvent.STARTED)
        try:
            self.display_worker.refresh(artifact_path)
        except Exception as error:
            self._save_pending_acknowledgement(
                PendingAcknowledgement(
                    event=JobEvent.FAILED.value,
                    job_id=str(desired.job_id),
                    revision=desired.revision,
                    error_code="display-refresh-failed",
                    error_message=str(error)[:1000],
                )
            )
            self._flush_pending_acknowledgement()
            raise

        # Persist completion before reporting it. A power loss or network failure
        # now leaves a retryable completion acknowledgement rather than ambiguity.
        self.state = AgentState(
            current_revision=desired.revision,
            last_successful_artifact_sha256=desired.artifact.sha256,
            last_heartbeat_at=self.state.last_heartbeat_at,
            pending_acknowledgement=PendingAcknowledgement(
                event=JobEvent.COMPLETED.value,
                job_id=str(desired.job_id),
                revision=desired.revision,
            ),
        )
        self.spool.save_state(self.state)
        self._flush_pending_acknowledgement()
        return True

    def _save_pending_acknowledgement(self, acknowledgement: PendingAcknowledgement | None) -> None:
        self.state = AgentState(
            current_revision=self.state.current_revision,
            last_successful_artifact_sha256=self.state.last_successful_artifact_sha256,
            last_heartbeat_at=self.state.last_heartbeat_at,
            pending_acknowledgement=acknowledgement,
        )
        self.spool.save_state(self.state)

    def _flush_pending_acknowledgement(self) -> None:
        pending = self.state.pending_acknowledgement
        if pending is None:
            return
        try:
            self.transport.acknowledge(
                pending.job_id,
                pending.job_event,
                revision=pending.revision,
                error_code=pending.error_code,
                error_message=pending.error_message,
            )
        except Exception:
            logger.warning("will retry pending display acknowledgement", extra={"job_id": pending.job_id})
            return
        self._save_pending_acknowledgement(None)

    def run_forever(self, notify: object) -> None:
        """Poll forever, using bounded exponential backoff for unavailable hosts."""

        failures = 0
        while True:
            try:
                self.run_once()
                failures = 0
                _notify(notify)
                time.sleep(self.settings.poll_interval_seconds)
            except KeyboardInterrupt:
                return
            except Exception:
                failures += 1
                delay = min(
                    self.settings.retry_initial_seconds * (2 ** min(failures - 1, 10)),
                    self.settings.retry_max_seconds,
                )
                logger.exception("Pi agent reconciliation failed; retrying", extra={"retry_seconds": delay})
                _notify(notify)
                time.sleep(delay)


def _notify(notify: object) -> None:
    watchdog = getattr(notify, "watchdog", None)
    if callable(watchdog):
        watchdog()
