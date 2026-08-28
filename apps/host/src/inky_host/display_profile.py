"""Fixed display configuration owned by the Docker host.

This module intentionally contains no Pi-side discovery or capability negotiation.
The server already knows the panel it is controlling.
"""

from inky_contract import (
    DisplayOrientation,
    DisplayProfile,
    DisplayRotation,
    PaletteColor,
    RenderSettings,
)

FIXED_DISPLAY_PROFILE = DisplayProfile(
    id="inky-main",
    name="Main Inky Display",
    width=800,
    height=480,
    palette=(
        PaletteColor.BLACK,
        PaletteColor.WHITE,
        PaletteColor.RED,
        PaletteColor.YELLOW,
        PaletteColor.BLUE,
        PaletteColor.GREEN,
        PaletteColor.ORANGE,
    ),
    orientation=DisplayOrientation.LANDSCAPE,
    rotation=DisplayRotation.DEGREES_0,
    default_render_settings=RenderSettings(),
    time_zone="Europe/Copenhagen",
)

