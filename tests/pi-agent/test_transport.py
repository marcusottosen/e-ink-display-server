import hashlib
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

from inky_contract import ArtifactDescriptor, ArtifactFormat, DesiredState, JobEvent, PaletteColor
from inky_pi_agent.config import AgentSettings
from inky_pi_agent.spool import AgentSpool
from inky_pi_agent.transport import HostClient


def test_host_client_uses_outbound_http_and_streams_verified_artifact(tmp_path: Path) -> None:
    output = BytesIO()
    Image.new("RGB", (800, 480), (12, 34, 56)).save(output, format="PNG")
    content = output.getvalue()
    sha256 = hashlib.sha256(content).hexdigest()
    desired = DesiredState(
        display_id="inky-main",
        revision=1,
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
    requests: list[httpx.Request] = []

    def host(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/desired"):
            return httpx.Response(200, json=desired.model_dump(mode="json"))
        if request.url.path.startswith("/api/v1/artifacts/"):
            return httpx.Response(200, content=content)
        return httpx.Response(200, json={"ok": True})

    settings = AgentSettings(server_url="http://host.test:8000", device_token="device-token")
    client = HostClient(settings, httpx.Client(transport=httpx.MockTransport(host)))
    try:
        received = client.desired_state(0)
        assert received is not None
        installed = client.download_artifact(received.artifact, AgentSpool(tmp_path / "spool"))
        client.heartbeat(1, sha256)
        client.acknowledge(str(received.job_id), JobEvent.COMPLETED, revision=1)
    finally:
        client.close()

    assert installed.is_file()
    assert [request.method for request in requests] == ["GET", "GET", "POST", "POST"]
    assert all(request.url.host == "host.test" for request in requests)
    assert all(request.headers["authorization"] == "Bearer device-token" for request in requests)
