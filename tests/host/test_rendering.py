from pathlib import Path

from PIL import Image

from inky_contract import (
    DisplayOrientation,
    DisplayProfile,
    DisplayRotation,
    PaletteColor,
    RenderSettings,
)
from inky_host.rendering import artifact_cache_key, render_image


def profile(rotation: DisplayRotation = DisplayRotation.DEGREES_0) -> DisplayProfile:
    return DisplayProfile(
        id="inky-main",
        name="Main Inky Display",
        width=800,
        height=480,
        palette=tuple(PaletteColor),
        orientation=DisplayOrientation.LANDSCAPE,
        rotation=rotation,
        default_render_settings=RenderSettings(),
        time_zone="Europe/Copenhagen",
    )


def test_render_is_deterministic_and_paletted(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (1200, 700), (120, 70, 220)).save(source)

    first = render_image(source, "a" * 64, profile(), RenderSettings())
    second = render_image(source, "a" * 64, profile(), RenderSettings())

    assert first.content == second.content
    assert first.sha256 == second.sha256
    assert (first.width, first.height) == (800, 480)


def test_rotation_changes_the_cache_key_and_retains_hardware_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (700, 1200), (120, 70, 220)).save(source)
    settings = RenderSettings()

    landscape = profile()
    rotated = profile(DisplayRotation.DEGREES_90)
    artifact = render_image(source, "b" * 64, rotated, settings)

    assert artifact_cache_key("b" * 64, landscape, settings) != artifact_cache_key("b" * 64, rotated, settings)
    assert (artifact.width, artifact.height) == (800, 480)
