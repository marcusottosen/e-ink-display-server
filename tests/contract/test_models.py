from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from inky_contract import (
    AgentHeartbeat,
    ArtifactDescriptor,
    ArtifactFormat,
    DesiredState,
    DisplayOrientation,
    DisplayProfile,
    DisplayRotation,
    PaletteColor,
    RenderSettings,
)

SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
PALETTE = (
    PaletteColor.BLACK,
    PaletteColor.WHITE,
    PaletteColor.RED,
    PaletteColor.YELLOW,
    PaletteColor.BLUE,
    PaletteColor.GREEN,
    PaletteColor.ORANGE,
)


def test_fixed_profile_has_the_expected_panel_configuration() -> None:
    profile = DisplayProfile(
        id="inky-main",
        name="Main Inky Display",
        width=800,
        height=480,
        palette=PALETTE,
        orientation=DisplayOrientation.LANDSCAPE,
        rotation=DisplayRotation.DEGREES_0,
        default_render_settings=RenderSettings(),
        time_zone="Europe/Copenhagen",
    )

    assert profile.width == 800
    assert profile.height == 480
    assert len(profile.palette) == 7


def test_desired_state_requires_a_sha256_bound_artifact_url() -> None:
    artifact = ArtifactDescriptor(
        sha256=SHA256,
        url=f"/api/v1/artifacts/{SHA256}",
        format=ArtifactFormat.PALETTED_PNG,
        width=800,
        height=480,
        palette=PALETTE,
        renderer_version="1.0.0",
    )

    desired = DesiredState(
        display_id="inky-main",
        revision=1,
        job_id=uuid4(),
        artifact=artifact,
    )

    assert desired.api_version == "v1"


def test_heartbeat_rejects_an_invalid_checksum() -> None:
    with pytest.raises(ValidationError):
        AgentHeartbeat(
            current_revision=0,
            last_successful_artifact_sha256="not-a-checksum",
            sent_at=datetime.now(UTC),
        )

