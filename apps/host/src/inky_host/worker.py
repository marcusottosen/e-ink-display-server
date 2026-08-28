"""Serialized in-process render worker for the single-display prototype."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from inky_contract import DisplayProfile, RenderSettings

from .database import ArtifactRecord, AssetRecord, DisplayJobRecord, DisplayRecord, record_activity
from .profiles import profile_from_record
from .rendering import RENDERER_VERSION, artifact_cache_key, render_image, validate_source_image
from .storage import Storage

logger = logging.getLogger(__name__)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RENDERING = "rendering"
    READY = "ready"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


def utc_now() -> datetime:
    return datetime.now(UTC)


class RenderWorker:
    def __init__(self, sessions: sessionmaker[Session], storage: Storage, max_source_pixels: int) -> None:
        self._sessions = sessions
        self._storage = storage
        self._max_source_pixels = max_source_pixels
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        pending_job_ids = await asyncio.to_thread(self._recover_unfinished_jobs)
        self._task = asyncio.create_task(self._run(), name="inky-render-worker")
        for job_id in pending_job_ids:
            await self.enqueue(job_id)

    async def stop(self) -> None:
        await self._queue.put(None)
        if self._task is not None:
            await self._task
            self._task = None

    async def enqueue(self, job_id: str) -> None:
        await self._queue.put(job_id)

    def prepare_asset_preview(
        self,
        session: Session,
        asset: AssetRecord,
        display: DisplayRecord,
        settings: RenderSettings,
    ) -> ArtifactRecord:
        """Create or reuse the exact display artifact used as an asset preview."""

        asset.width, asset.height = validate_source_image(
            self._storage.path(asset.storage_path), self._max_source_pixels
        )
        return self._cached_or_render(session, asset, profile_from_record(display), settings)

    def _recover_unfinished_jobs(self) -> list[str]:
        """Put jobs interrupted by a host restart back into the local queue."""

        with self._sessions() as session:
            interrupted_jobs = session.scalars(
                select(DisplayJobRecord).where(DisplayJobRecord.status == JobStatus.RENDERING)
            ).all()
            for job in interrupted_jobs:
                job.status = JobStatus.QUEUED
                record_activity(
                    session,
                    "artifact.render-requeued",
                    f"Requeued interrupted render for display job {job.id}",
                    display_id=job.display_id,
                    asset_id=job.asset_id,
                    job_id=job.id,
                )
            queued_job_ids = session.scalars(
                select(DisplayJobRecord.id).where(DisplayJobRecord.status == JobStatus.QUEUED)
            ).all()
            session.commit()
        return queued_job_ids

    async def _run(self) -> None:
        while (job_id := await self._queue.get()) is not None:
            try:
                await asyncio.to_thread(self._process, job_id)
            except Exception as error:
                logger.exception("render worker stopped processing a job", extra={"job_id": job_id})
                await asyncio.to_thread(self._fail_unhandled_job, job_id, str(error))
            finally:
                self._queue.task_done()

    def _fail_unhandled_job(self, job_id: str, message: str) -> None:
        with self._sessions() as session:
            job = session.get(DisplayJobRecord, job_id)
            if job is not None and job.status in {JobStatus.QUEUED, JobStatus.RENDERING}:
                self._fail(session, job, "worker-failed", message)

    def _process(self, job_id: str) -> None:
        with self._sessions() as session:
            job = session.get(DisplayJobRecord, job_id)
            if job is None or job.status != JobStatus.QUEUED:
                return
            job.status = JobStatus.RENDERING
            session.commit()

            asset = session.get(AssetRecord, job.asset_id)
            display = session.get(DisplayRecord, job.display_id)
            if asset is None or display is None:
                self._fail(session, job, "missing-record", "Asset or display is no longer available")
                return

            try:
                settings = RenderSettings.model_validate(job.render_settings)
                artifact = self.prepare_asset_preview(session, asset, display, settings)
            except Exception as error:
                session.rollback()
                failed_job = session.get(DisplayJobRecord, job_id)
                if failed_job is not None and failed_job.status != JobStatus.SUPERSEDED:
                    self._fail(session, failed_job, "render-failed", str(error))
                return

            session.refresh(job)
            if job.status == JobStatus.SUPERSEDED:
                return

            job.artifact_id = artifact.id
            display.desired_revision += 1
            display.desired_job_id = job.id
            display.desired_artifact_id = artifact.id
            job.revision = display.desired_revision
            job.status = JobStatus.READY
            record_activity(
                session,
                "artifact.ready",
                f"Prepared artifact for '{asset.original_filename}'",
                display_id=display.id,
                asset_id=asset.id,
                job_id=job.id,
            )
            session.commit()

    def _cached_or_render(
        self,
        session: Session,
        asset: AssetRecord,
        profile: DisplayProfile,
        settings: RenderSettings,
    ) -> ArtifactRecord:
        cache_key = artifact_cache_key(asset.sha256, profile, settings)
        existing = session.scalar(select(ArtifactRecord).where(ArtifactRecord.cache_key == cache_key))
        if existing is not None:
            if (
                self._storage.path(existing.storage_path).is_file()
                and self._storage.preview_path(existing.sha256).is_file()
            ):
                return existing
            rendered = render_image(
                self._storage.path(asset.storage_path),
                asset.sha256,
                profile,
                settings,
            )
            existing.storage_path = self._storage.write_artifact(rendered.content, rendered.sha256)
            self._storage.write_preview(rendered.preview_content, rendered.sha256)
            return existing

        rendered = render_image(
            self._storage.path(asset.storage_path),
            asset.sha256,
            profile,
            settings,
        )

        same_content = session.scalar(
            select(ArtifactRecord).where(
                ArtifactRecord.asset_id == asset.id,
                ArtifactRecord.sha256 == rendered.sha256,
            )
        )
        if same_content is not None:
            if not self._storage.path(same_content.storage_path).is_file():
                same_content.storage_path = self._storage.write_artifact(rendered.content, rendered.sha256)
            if not self._storage.preview_path(same_content.sha256).is_file():
                self._storage.write_preview(rendered.preview_content, rendered.sha256)
            return same_content

        relative_path = self._storage.write_artifact(rendered.content, rendered.sha256)
        self._storage.write_preview(rendered.preview_content, rendered.sha256)
        artifact = ArtifactRecord(
            id=str(uuid4()),
            asset_id=asset.id,
            cache_key=rendered.cache_key,
            sha256=rendered.sha256,
            storage_path=relative_path,
            renderer_version=RENDERER_VERSION,
            render_settings=settings.model_dump(mode="json"),
            width=rendered.width,
            height=rendered.height,
            palette=[color.value for color in profile.palette],
        )
        session.add(artifact)
        session.flush()
        return artifact

    @staticmethod
    def _fail(session: Session, job: DisplayJobRecord, code: str, message: str) -> None:
        job.status = JobStatus.FAILED
        job.error_code = code
        job.error_message = message[:1000]
        job.failed_at = utc_now()
        record_activity(
            session,
            "artifact.failed",
            f"Could not render asset for display job {job.id}",
            display_id=job.display_id,
            asset_id=job.asset_id,
            job_id=job.id,
        )
        session.commit()


def create_display_now_job(
    session: Session,
    display: DisplayRecord,
    asset: AssetRecord,
    settings: RenderSettings,
    album_id: str | None = None,
) -> DisplayJobRecord:
    """Queue a job and remove earlier unfinished work from desired state."""

    stale_jobs = session.scalars(
        select(DisplayJobRecord).where(
            DisplayJobRecord.display_id == display.id,
            DisplayJobRecord.status.in_([JobStatus.QUEUED, JobStatus.RENDERING, JobStatus.READY]),
        )
    )
    stale_job_ids: set[str] = set()
    for stale_job in stale_jobs:
        stale_job.status = JobStatus.SUPERSEDED
        stale_job_ids.add(stale_job.id)
    if display.desired_job_id in stale_job_ids:
        display.desired_job_id = None
        display.desired_artifact_id = None

    job = DisplayJobRecord(
        id=str(uuid4()),
        display_id=display.id,
        asset_id=asset.id,
        album_id=album_id,
        status=JobStatus.QUEUED,
        render_settings=settings.model_dump(mode="json"),
    )
    session.add(job)
    session.commit()
    return job
