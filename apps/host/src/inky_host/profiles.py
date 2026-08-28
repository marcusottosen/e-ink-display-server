"""Conversion between persisted display settings and the shared display profile."""

from __future__ import annotations

from inky_contract import (
    DisplayOrientation,
    DisplayProfile,
    DisplayRotation,
    PaletteColor,
    RenderSettings,
)

from .database import DisplayRecord


def profile_from_record(display: DisplayRecord) -> DisplayProfile:
    return DisplayProfile(
        id=display.id,
        name=display.name,
        width=800,
        height=480,
        palette=tuple(PaletteColor),
        orientation=DisplayOrientation(display.orientation),
        rotation=DisplayRotation(display.rotation),
        default_render_settings=RenderSettings.model_validate(display.default_render_settings),
        time_zone=display.time_zone,
    )
