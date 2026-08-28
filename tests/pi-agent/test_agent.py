import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from inky_contract import (
    ArtifactDescriptor,
    ArtifactFormat,
    DesiredState,
    JobEvent,
    PaletteColor,
)
from inky_pi_agent.agent import InkyAgent
from inky_pi_agent.config import AgentSettings
from inky_pi_agent.hardware import SerializedDisplayWorker
from inky_pi_agent.spool import AgentSpool


def image_bytes(size: tuple[int, int] = (800, 480)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (80, 150, 210)).save(output, format="PNG")
    return output.getvalue()


def desired_state(image: bytes, revision: int = 1) -> DesiredState:
    sha256 = hashlib.sha256(image).hexdigest()
    return DesiredState(
        display_id="inky-main",
        revision=revision,
        job_id="3d503150-b72e-425f-b819-472b74ef27c2",
        artifact=ArtifactDescriptor(
            sha256=sha256,
            url=f"/api/v1/artifacts/{sha256}",
            format=ArtifactFormat.RGB_PNG,
            width=800,
            height=480,
            palette=tuple(PaletteColor),
            renderer_version="1.1.0",
        ),
    )


class FakeTransport:
    def __init__(self, desired: DesiredState, content: bytes, *, fail_first_completion: bool = False) -> None:
        self.desired = desired
        self.content = content
        self.fail_first_completion = fail_first_completion
        self.events: list[JobEvent] = []
        self.heartbeats: list[int] = []

    def desired_state(self, current_revision: int) -> DesiredState | None:
        return self.desired if current_revision < self.desired.revision else None

    def download_artifact(self, descriptor: ArtifactDescriptor, spool: AgentSpool) -> Path:
        return spool.install_download(descriptor, [self.content[:100], self.content[100:]])

    def heartbeat(self, current_revision: int, artifact_sha256: str | None) -> None:
        self.heartbeats.append(current_revision)

    def acknowledge(
        self,
        job_id: str,
        event: JobEvent,
        *,
        revision: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if event is JobEvent.COMPLETED and self.fail_first_completion:
            self.fail_first_completion = False
            raise OSError("host unavailable")
        self.events.append(event)


class FakeDisplay:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.shown: list[Path] = []

    def show(self, image_path: Path) -> None:
        self.shown.append(image_path)
        if self.fail:
            raise RuntimeError("E673 busy timeout")


def make_agent(tmp_path: Path, transport: FakeTransport, display: FakeDisplay) -> InkyAgent:
    settings = AgentSettings(
        server_url="http://host.test:8000",
        data_dir=tmp_path / "spool",
        poll_interval_seconds=5,
        heartbeat_interval_seconds=5,
        hardware_enabled=False,
    )
    spool = AgentSpool(settings.data_dir)
    return InkyAgent(settings, transport, spool, SerializedDisplayWorker(display))


def test_agent_downloads_verifies_refreshes_and_persists_completion(tmp_path: Path) -> None:
    content = image_bytes()
    transport = FakeTransport(desired_state(content), content)
    display = FakeDisplay()
    agent = make_agent(tmp_path, transport, display)

    assert agent.run_once() is True
    assert transport.events == [JobEvent.STARTED, JobEvent.COMPLETED]
    assert transport.heartbeats == [0]
    assert len(display.shown) == 1
    assert agent.spool.load_state().current_revision == 1
    assert agent.spool.has_artifact(agent.spool.load_state().last_successful_artifact_sha256)


def test_agent_retries_uncertain_completion_after_a_network_failure(tmp_path: Path) -> None:
    content = image_bytes()
    transport = FakeTransport(desired_state(content), content, fail_first_completion=True)
    agent = make_agent(tmp_path, transport, FakeDisplay())

    assert agent.run_once() is True
    assert agent.spool.load_state().pending_acknowledgement is not None
    assert agent.run_once() is False
    assert transport.events == [JobEvent.STARTED, JobEvent.COMPLETED]
    assert agent.spool.load_state().pending_acknowledgement is None


def test_agent_reports_a_hardware_refresh_failure(tmp_path: Path) -> None:
    content = image_bytes()
    transport = FakeTransport(desired_state(content), content)
    agent = make_agent(tmp_path, transport, FakeDisplay(fail=True))

    with pytest.raises(RuntimeError, match="busy timeout"):
        agent.run_once()
    assert transport.events == [JobEvent.STARTED, JobEvent.FAILED]


def test_spool_rejects_checksum_or_dimension_errors_without_installing(tmp_path: Path) -> None:
    spool = AgentSpool(tmp_path / "spool")
    content = image_bytes((799, 480))
    descriptor = desired_state(image_bytes()).artifact

    with pytest.raises(ValueError, match="checksum"):
        spool.install_download(descriptor, [content])
    assert not spool.has_artifact(descriptor.sha256)

    wrong_size = desired_state(content).artifact
    with pytest.raises(ValueError, match="dimensions"):
        spool.install_download(wrong_size, [content])
    assert not spool.has_artifact(wrong_size.sha256)
