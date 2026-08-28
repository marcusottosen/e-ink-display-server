"""Safe, content-addressed filesystem storage."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


@dataclass(frozen=True)
class StoredUpload:
    filename: str
    mime_type: str
    sha256: str
    file_size: int
    relative_path: str


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.originals = root / "originals"
        self.artifacts = root / "artifacts"
        self.tmp = root / "tmp"
        for directory in (self.originals, self.artifacts, self.tmp):
            directory.mkdir(parents=True, exist_ok=True)

    def path(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        if self.root.resolve() not in candidate.parents:
            raise ValueError("storage path escapes the data directory")
        return candidate

    async def save_upload(self, upload: UploadFile, max_bytes: int) -> StoredUpload:
        mime_type = upload.content_type or ""
        if mime_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Only JPEG, PNG, and WebP image uploads are supported",
            )

        filename = Path(upload.filename or "upload").name[:255]
        temporary_path = self.tmp / f"{uuid4()}.upload"
        digest = hashlib.sha256()
        file_size = 0

        try:
            with temporary_path.open("xb") as output:
                while chunk := await upload.read(1024 * 1024):
                    file_size += len(chunk)
                    if file_size > max_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Upload exceeds the {max_bytes // (1024 * 1024)} MiB limit",
                        )
                    digest.update(chunk)
                    output.write(chunk)

            sha256 = digest.hexdigest()
            relative_path = f"originals/{sha256[:2]}/{sha256}"
            destination = self.path(relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                temporary_path.unlink()
            else:
                os.replace(temporary_path, destination)
            return StoredUpload(filename, mime_type, sha256, file_size, relative_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

    def write_artifact(self, content: bytes, sha256: str) -> str:
        relative_path = f"artifacts/{sha256[:2]}/{sha256}.png"
        return self._write_derived(content, relative_path)

    def preview_path(self, artifact_sha256: str) -> Path:
        return self.path(f"artifacts/{artifact_sha256[:2]}/{artifact_sha256}.preview.png")

    def write_preview(self, content: bytes, artifact_sha256: str) -> str:
        relative_path = f"artifacts/{artifact_sha256[:2]}/{artifact_sha256}.preview.png"
        return self._write_derived(content, relative_path)

    def _write_derived(self, content: bytes, relative_path: str) -> str:
        destination = self.path(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            return relative_path

        temporary_path = self.tmp / f"{uuid4()}.artifact"
        try:
            with temporary_path.open("xb") as output:
                output.write(content)
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
        return relative_path
