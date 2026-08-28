# Host and Pi messages

This package contains the Pydantic models used by the Docker host and the one
Raspberry Pi. The panel model, resolution, orientation, and display ID are fixed
in host configuration. The Pi does not discover or register a display.

The host API lives under `/api/v1`. It uses `snake_case` JSON, UTC ISO 8601
timestamps, UUIDs, and lowercase 64-character SHA-256 values.

## Pi requests

| Method | Route | What it does |
| --- | --- | --- |
| `GET` | `/api/v1/displays/{display_id}/desired` | Gets the newest requested image, if one is needed. |
| `GET` | `/api/v1/artifacts/{sha256}` | Downloads the PNG for that request. |
| `POST` | `/api/v1/displays/{display_id}/heartbeat` | Reports that the Pi is still checking in. |
| `POST` | `/api/v1/displays/{display_id}/jobs/{job_id}/started` | Says the Pi has started the refresh. |
| `POST` | `/api/v1/displays/{display_id}/jobs/{job_id}/completed` | Says the panel refresh call returned. |
| `POST` | `/api/v1/displays/{display_id}/jobs/{job_id}/failed` | Reports an error. |

The Pi asks for only the newest requested image. If a completion report is lost,
the Pi may receive the same image again; showing it again is fine.

## Image details

The panel is fixed at 800 × 480. The host changes framing, rotation, and size,
but does not alter colours, apply dithering, enhance images, or choose crops.
The generated PNG remains RGB; the Inky driver handles the physical panel's own
colour mapping during refresh.

`display_orientation` means how the panel is installed. `content_rotation` and
`fit_mode` are choices for an individual image. The browser helper and generated
PNG use the same framing and orientation values.

## Desired image example

```json
{
  "api_version": "v1",
  "display_id": "inky-main",
  "revision": 42,
  "job_id": "9a595797-c181-4f53-8927-2a6fe776c65b",
  "artifact": {
    "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    "url": "/api/v1/artifacts/ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    "format": "rgb-png",
    "media_type": "image/png",
    "width": 800,
    "height": 480,
    "palette": ["black", "white", "red", "yellow", "blue", "green", "orange"],
    "renderer_version": "1.0.0"
  }
}
```

## Host request

`POST /api/v1/displays/{display_id}/display-now` accepts an existing gallery
image ID and optional framing settings:

```json
{
  "asset_id": "9a595797-c181-4f53-8927-2a6fe776c65b",
  "render_settings": {
    "fit_mode": "crop",
    "content_rotation": 0,
    "focal_point_x": 0.5,
    "focal_point_y": 0.5,
    "flip_horizontal": false,
    "flip_vertical": false
  }
}
```
