"""Serialized in-process render worker for the single-display prototype."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from inky_contract import DisplayProfile, RenderSettings

from .database import ArtifactRecord, AssetRecord, DisplayJobRecord, DisplayRecord
from .profiles import profile_from_record
from .rendering import RENDERER_VERSION, artifact_cache_key, render_image, validate_source_image
from .storage import Storage


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
        self._task = asyncio.create_task(self._run(), name="inky-render-worker")

    async def stop(self) -> None:
        await self._queue.put(None)
        if self._task is not None:
            await self._task
            self._task = None

    async def enqueue(self, job_id: str) -> None:
        await self._queue.put(job_id)

    async def _run(self) -> None:
        while (job_id := await self._queue.get()) is not None:
            try:
                await asyncio.to_thread(self._process, job_id)
            finally:
                self._queue.task_done()

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
                profile = profile_from_record(display)
                settings = RenderSettings.model_validate(job.render_settings)
                asset.width, asset.height = validate_source_image(
                    self._storage.path(asset.storage_path), self._max_source_pixels
                )
                artifact = self._cached_or_render(session, asset, profile, settings)
            except Exception as error:
                self._fail(session, job, "render-failed", str(error))
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
        session.commit()


def create_display_now_job(
    session: Session, display: DisplayRecord, asset: AssetRecord, settings: RenderSettings
) -> DisplayJobRecord:
    """Queue a job and invalidate work that can no longer become desired state."""

    stale_jobs = session.scalars(
        select(DisplayJobRecord).where(
            DisplayJobRecord.display_id == display.id,
            DisplayJobRecord.status.in_([JobStatus.QUEUED, JobStatus.RENDERING]),
        )
    )
    for stale_job in stale_jobs:
        stale_job.status = JobStatus.SUPERSEDED

    job = DisplayJobRecord(
        id=str(uuid4()),
        display_id=display.id,
        asset_id=asset.id,
        status=JobStatus.QUEUED,
        render_settings=settings.model_dump(mode="json"),
    )
    session.add(job)
    session.commit()
    return job
