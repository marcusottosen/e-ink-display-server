"""Deterministic, host-side image rendering for the fixed panel profile."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from inky_contract import DisplayProfile, RenderSettings

RENDERER_VERSION = "1.1.0"


@dataclass(frozen=True)
class RenderedArtifact:
    content: bytes
    preview_content: bytes
    sha256: str
    cache_key: str
    width: int
    height: int


def artifact_cache_key(source_sha256: str, profile: DisplayProfile, settings: RenderSettings) -> str:
    payload = {
        "source_sha256": source_sha256,
        "profile": profile.model_dump(mode="json"),
        "settings": settings.model_dump(mode="json"),
        "renderer_version": RENDERER_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def render_image(
    source_path: Path, source_sha256: str, profile: DisplayProfile, settings: RenderSettings
) -> RenderedArtifact:
    """Resize and orient an original image into a deterministic RGB PNG artifact.

    The host preserves source colours. The physical E-Ink driver's unavoidable
    palette mapping happens only when the Pi performs the hardware refresh.
    """

    with Image.open(source_path) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        image = _rotate_content(image, int(settings.content_rotation))
        image = _frame_image(image, _logical_dimensions(profile), settings)
        if settings.flip_horizontal:
            image = ImageOps.mirror(image)
        if settings.flip_vertical:
            image = ImageOps.flip(image)
        preview_content = _encode_png(image)
        image = _rotate_to_hardware(image, int(profile.rotation))

    if image.size != (profile.width, profile.height):
        raise ValueError("rendered artifact does not match the fixed display dimensions")

    content = _encode_png(image)
    return RenderedArtifact(
        content=content,
        preview_content=preview_content,
        sha256=hashlib.sha256(content).hexdigest(),
        cache_key=artifact_cache_key(source_sha256, profile, settings),
        width=image.width,
        height=image.height,
    )


def validate_source_image(source_path: Path, max_pixels: int) -> tuple[int, int]:
    """Validate the uploaded bytes as a decodable image before rendering it."""

    with Image.open(source_path) as image:
        width, height = image.size
        if width * height > max_pixels:
            raise ValueError(f"source image exceeds the {max_pixels:,} pixel limit")
        image.verify()
    return width, height


def _encode_png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def _logical_dimensions(profile: DisplayProfile) -> tuple[int, int]:
    if int(profile.rotation) in (90, 270):
        return profile.height, profile.width
    return profile.width, profile.height


def _rotate_content(image: Image.Image, degrees: int) -> Image.Image:
    if degrees:
        return image.rotate(-degrees, expand=True)
    return image


def _rotate_to_hardware(image: Image.Image, degrees: int) -> Image.Image:
    if degrees:
        return image.rotate(-degrees, expand=True)
    return image


def _frame_image(image: Image.Image, target: tuple[int, int], settings: RenderSettings) -> Image.Image:
    target_width, target_height = target
    source_width, source_height = image.size

    if settings.fit_mode.value == "stretch":
        return image.resize(target, Image.Resampling.LANCZOS)

    if settings.fit_mode.value == "contain":
        scale = min(target_width / source_width, target_height / source_height)
        resized = image.resize((round(source_width * scale), round(source_height * scale)), Image.Resampling.LANCZOS)
        framed = Image.new("RGB", target, "white")
        framed.paste(resized, ((target_width - resized.width) // 2, (target_height - resized.height) // 2))
        return framed

    scale = max(target_width / source_width, target_height / source_height)
    resized = image.resize((round(source_width * scale), round(source_height * scale)), Image.Resampling.LANCZOS)
    left = round((resized.width - target_width) * settings.focal_point_x)
    top = round((resized.height - target_height) * settings.focal_point_y)
    left = min(max(left, 0), resized.width - target_width)
    top = min(max(top, 0), resized.height - target_height)
    return resized.crop((left, top, left + target_width, top + target_height))
