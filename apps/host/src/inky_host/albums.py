"""Album persistence, safe asset references, and the single-process album runner."""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from inky_contract import RenderSettings

from .api_models import AlbumItemResponse, AlbumOrderMode, AlbumResponse, AssetResponse
from .database import (
    AlbumItemRecord,
    AlbumRecord,
    ArtifactRecord,
    AssetRecord,
    DisplayJobRecord,
    DisplayRecord,
    record_activity,
)
from .worker import JobStatus, RenderWorker, create_display_now_job


def utc_now() -> datetime:
    return datetime.now(UTC)


def asset_response(asset: AssetRecord, blockers: list[str] | None = None) -> AssetResponse:
    return AssetResponse(
        id=asset.id,
        original_filename=asset.original_filename,
        sha256=asset.sha256,
        mime_type=asset.mime_type,
        file_size=asset.file_size,
        width=asset.width,
        height=asset.height,
        created_at=asset.created_at,
        deleted_at=asset.deleted_at,
        preview_url=f"/api/v1/assets/{asset.id}/preview" if asset.width is not None else None,
        deletion_blockers=blockers or [],
    )


def deletion_blockers(session: Session, asset: AssetRecord) -> list[str]:
    """Return active references that make a soft delete ambiguous or unsafe."""

    blockers: list[str] = []
    running_albums = session.scalars(
        select(AlbumRecord.name)
        .join(AlbumItemRecord, AlbumItemRecord.album_id == AlbumRecord.id)
        .where(AlbumItemRecord.asset_id == asset.id, AlbumRecord.is_running.is_(True))
    ).all()
    blockers.extend(f"used by running album: {name}" for name in running_albums)

    displays = session.scalars(select(DisplayRecord)).all()
    for display in displays:
        if display.desired_artifact_id:
            artifact = session.get(ArtifactRecord, display.desired_artifact_id)
            if artifact and artifact.asset_id == asset.id:
                blockers.append(f"currently desired on display: {display.name}")
        if display.current_revision:
            current_job = session.scalar(
                select(DisplayJobRecord).where(
                    DisplayJobRecord.display_id == display.id,
                    DisplayJobRecord.revision == display.current_revision,
                )
            )
            if current_job and current_job.asset_id == asset.id:
                blockers.append(f"currently shown on display: {display.name}")

    active_job = session.scalar(
        select(DisplayJobRecord.id).where(
            DisplayJobRecord.asset_id == asset.id,
            DisplayJobRecord.status.in_([JobStatus.QUEUED, JobStatus.RENDERING, JobStatus.READY, JobStatus.STARTED]),
        )
    )
    if active_job:
        blockers.append("used by an active display job")
    return list(dict.fromkeys(blockers))


def album_response(session: Session, album: AlbumRecord) -> AlbumResponse:
    items = session.scalars(
        select(AlbumItemRecord).where(AlbumItemRecord.album_id == album.id).order_by(AlbumItemRecord.position)
    ).all()
    responses: list[AlbumItemResponse] = []
    for item in items:
        asset = session.get(AssetRecord, item.asset_id)
        if asset is not None:
            responses.append(
                AlbumItemResponse(
                    id=item.id,
                    asset_id=item.asset_id,
                    position=item.position,
                    asset=asset_response(asset),
                )
            )
    return AlbumResponse(
        id=album.id,
        display_id=album.display_id,
        name=album.name,
        order_mode=AlbumOrderMode(album.order_mode),
        interval_seconds=album.interval_seconds,
        enabled=album.enabled,
        is_running=album.is_running,
        time_zone=album.time_zone,
        schedule_start_at=album.schedule_start_at,
        schedule_end_at=album.schedule_end_at,
        default_render_settings=RenderSettings.model_validate(album.default_render_settings),
        next_item_index=album.next_item_index,
        next_run_at=album.next_run_at,
        items=responses,
        created_at=album.created_at,
        updated_at=album.updated_at,
    )


class AlbumScheduler:
    """Queues one album item at a time; physical refreshes remain worker-serialized."""

    def __init__(self, sessions: sessionmaker[Session], worker: RenderWorker) -> None:
        self._sessions = sessions
        self._worker = worker
        self._task: asyncio.Task[None] | None = None
        self._random = random.SystemRandom()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="inky-album-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_album(self, album_id: str) -> str | None:
        job_id = await asyncio.to_thread(self._start_and_queue, album_id)
        if job_id is not None:
            await self._worker.enqueue(job_id)
        return job_id

    async def stop_album(self, album_id: str) -> None:
        await asyncio.to_thread(self._stop_album, album_id)

    async def _run(self) -> None:
        while True:
            job_ids = await asyncio.to_thread(self._queue_due_items)
            for job_id in job_ids:
                await self._worker.enqueue(job_id)
            await asyncio.sleep(2)

    def _start_and_queue(self, album_id: str) -> str | None:
        with self._sessions() as session:
            album = session.get(AlbumRecord, album_id)
            if album is None:
                return None
            for other in session.scalars(
                select(AlbumRecord).where(
                    AlbumRecord.display_id == album.display_id,
                    AlbumRecord.is_running.is_(True),
                )
            ):
                other.is_running = False
            album.is_running = True
            album.enabled = True
            now = utc_now()
            if album.schedule_end_at and now >= album.schedule_end_at:
                album.is_running = False
                session.commit()
                return None
            if album.schedule_start_at and now < album.schedule_start_at:
                album.next_run_at = album.schedule_start_at
                job_id = None
            else:
                job_id = self._queue_next_item(session, album, now)
            record_activity(
                session,
                "album.started",
                f"Started album '{album.name}'",
                display_id=album.display_id,
                album_id=album.id,
                job_id=job_id,
            )
            session.commit()
            return job_id

    def _stop_album(self, album_id: str) -> None:
        with self._sessions() as session:
            album = session.get(AlbumRecord, album_id)
            if album is None:
                return
            album.is_running = False
            album.next_run_at = None
            record_activity(
                session,
                "album.stopped",
                f"Stopped album '{album.name}'",
                display_id=album.display_id,
                album_id=album.id,
            )
            session.commit()

    def _queue_due_items(self) -> list[str]:
        now = utc_now()
        job_ids: list[str] = []
        with self._sessions() as session:
            albums = session.scalars(
                select(AlbumRecord).where(AlbumRecord.is_running.is_(True), AlbumRecord.enabled.is_(True))
            ).all()
            for album in albums:
                if album.schedule_start_at and now < album.schedule_start_at:
                    continue
                if album.schedule_end_at and now >= album.schedule_end_at:
                    album.is_running = False
                    album.next_run_at = None
                    record_activity(
                        session,
                        "album.schedule-ended",
                        f"Stopped album '{album.name}' because its schedule window ended",
                        display_id=album.display_id,
                        album_id=album.id,
                    )
                    continue
                if album.next_run_at is None or album.next_run_at <= now:
                    job_id = self._queue_next_item(session, album, now)
                    if job_id is not None:
                        job_ids.append(job_id)
            session.commit()
        return job_ids

    def _queue_next_item(self, session: Session, album: AlbumRecord, now: datetime) -> str | None:
        items = session.scalars(
            select(AlbumItemRecord).where(AlbumItemRecord.album_id == album.id).order_by(AlbumItemRecord.position)
        ).all()
        valid_items = [item for item in items if _is_available_asset(session, item.asset_id)]
        if not valid_items:
            album.is_running = False
            record_activity(
                session,
                "album.stopped-empty",
                f"Stopped album '{album.name}' because it has no available images",
                display_id=album.display_id,
                album_id=album.id,
            )
            return None

        if album.order_mode == AlbumOrderMode.SHUFFLE:
            item = self._random.choice(valid_items)
        else:
            item = valid_items[album.next_item_index % len(valid_items)]
            album.next_item_index = (album.next_item_index + 1) % len(valid_items)

        display = session.get(DisplayRecord, album.display_id)
        asset = session.get(AssetRecord, item.asset_id)
        if display is None or asset is None:
            return None
        settings = RenderSettings.model_validate(album.default_render_settings)
        job = create_display_now_job(session, display, asset, settings)
        album.next_run_at = now + timedelta(seconds=album.interval_seconds)
        record_activity(
            session,
            "album.item-queued",
            f"Queued '{asset.original_filename}' from album '{album.name}'",
            display_id=album.display_id,
            asset_id=asset.id,
            album_id=album.id,
            job_id=job.id,
        )
        return job.id


def _is_available_asset(session: Session, asset_id: str) -> bool:
    asset = session.get(AssetRecord, asset_id)
    return asset is not None and asset.deleted_at is None
