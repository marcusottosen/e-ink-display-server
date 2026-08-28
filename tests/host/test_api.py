import time
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from inky_contract import JobAcknowledgement, JobEvent
from inky_host.config import Settings
from inky_host.main import create_app


def png_upload() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1000, 700), (30, 110, 200)).save(output, format="PNG")
    return output.getvalue()


def test_health_and_upload_to_desired_state(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        agent_device_token="test-device-token",
        environment="test",
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/health", headers={"X-Request-ID": "test-correlation"})
        assert health.json()["status"] == "ok"
        assert health.headers["X-Request-ID"] == "test-correlation"

        upload = client.post(
            "/api/v1/assets",
            files={"file": ("sky.png", png_upload(), "image/png")},
        )
        assert upload.status_code == 201
        asset_id = upload.json()["id"]

        queued = client.post(
            "/api/v1/displays/inky-main/display-now",
            json={"asset_id": asset_id, "render_settings": {"fit_mode": "contain"}},
        )
        assert queued.status_code == 200
        job_id = queued.json()["id"]

        for _ in range(30):
            job = client.get(f"/api/v1/jobs/{job_id}").json()
            if job["status"] in {"ready", "failed"}:
                break
            time.sleep(0.05)
        assert job["status"] == "ready"
        assert client.get(job["preview_url"]).headers["content-type"].startswith("image/png")

        headers = {"Authorization": "Bearer test-device-token"}
        desired = client.get("/api/v1/displays/inky-main/desired", headers=headers)
        assert desired.status_code == 200
        payload = desired.json()
        assert payload["artifact"]["width"] == 800
        assert client.get(payload["artifact"]["url"], headers=headers).status_code == 200

        started = JobAcknowledgement(event=JobEvent.STARTED, occurred_at="2026-01-01T00:00:00Z")
        assert (
            client.post(
                f"/api/v1/displays/inky-main/jobs/{job_id}/started",
                headers=headers,
                json=started.model_dump(mode="json"),
            ).status_code
            == 200
        )
        completed = JobAcknowledgement(
            event=JobEvent.COMPLETED,
            completed_revision=payload["revision"],
            occurred_at="2026-01-01T00:00:01Z",
        )
        assert (
            client.post(
                f"/api/v1/displays/inky-main/jobs/{job_id}/completed",
                headers=headers,
                json=completed.model_dump(mode="json"),
            ).status_code
            == 200
        )
        assert client.get("/api/v1/displays/inky-main").json()["current_revision"] == 1


def test_upload_rejects_unsupported_content_type(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", environment="test")
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/assets", files={"file": ("not-an-image.txt", b"hello", "text/plain")})
    assert response.status_code == 415


def test_portrait_setting_changes_the_browser_preview_orientation(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", environment="test")
    with TestClient(create_app(settings)) as client:
        settings_response = client.patch(
            "/api/v1/displays/inky-main/settings",
            json={"orientation": "portrait", "rotation": 90},
        )
        assert settings_response.status_code == 200
        assert settings_response.json()["orientation"] == "portrait"

        upload = client.post(
            "/api/v1/assets",
            files={"file": ("portrait.png", png_upload(), "image/png")},
        )
        queued = client.post(
            "/api/v1/displays/inky-main/display-now",
            json={"asset_id": upload.json()["id"]},
        )
        job_id = queued.json()["id"]
        for _ in range(30):
            job = client.get(f"/api/v1/jobs/{job_id}").json()
            if job["status"] in {"ready", "failed"}:
                break
            time.sleep(0.05)
        assert job["status"] == "ready"

        preview = Image.open(BytesIO(client.get(job["preview_url"]).content))
        assert preview.size == (480, 800)
