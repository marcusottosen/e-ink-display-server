# Inky contract v1

This package is the source of truth for messages exchanged between the Docker host
and the fixed Raspberry Pi agent. It intentionally contains no endpoint for display
discovery, model registration, or capability negotiation: the host already owns the
fixed display profile.

## Compatibility rules

- The API prefix is `/api/v1` and `api_version` is `v1`.
- Additive optional fields are allowed in a later compatible version.
- Renaming, removing, or changing the meaning of a field requires a new API version.
- JSON uses `snake_case`, UTC ISO 8601 timestamps, UUID identifiers, and lowercase
  64-character SHA-256 hex digests.
- The agent authenticates as its pre-configured display using a bearer token. Tokens
  are never part of a request body or response and must never be logged.

## Fixed display profile

The server configures each display's ID, 800 × 480 panel resolution, seven-colour
palette, physical orientation, rotation, default render settings, and time zone.
The Pi's requests identify only its already-known display route and authenticate
with its device token.

**Display orientation** describes the installed panel direction. **Content framing**
describes how an image is treated (crop, fit, focal point, flips). A host preview and
the delivered artifact must apply both sets of settings in the same order.

## Agent endpoints

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/displays/{display_id}/desired` | Retrieve the latest desired revision, or no-content when already current. |
| `GET` | `/api/v1/artifacts/{sha256}` | Download an immutable binary artifact. |
| `POST` | `/api/v1/displays/{display_id}/heartbeat` | Send liveness and current-revision state. |
| `POST` | `/api/v1/displays/{display_id}/jobs/{job_id}/started` | Acknowledge display work has begun. |
| `POST` | `/api/v1/displays/{display_id}/jobs/{job_id}/completed` | Confirm `show()` returned for the revision. |
| `POST` | `/api/v1/displays/{display_id}/jobs/{job_id}/failed` | Report a verified failure. |

The desired-state endpoint delivers only the most recent valid revision. Delivery is
at-least-once: receiving a previously displayed revision must be safe, and a lost
completion acknowledgement must not discard the artifact.

## Desired-state response

```json
{
  "api_version": "v1",
  "display_id": "inky-main",
  "revision": 42,
  "job_id": "9a595797-c181-4f53-8927-2a6fe776c65b",
  "artifact": {
    "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    "url": "/api/v1/artifacts/ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    "format": "paletted-png",
    "media_type": "image/png",
    "width": 800,
    "height": 480,
    "palette": ["black", "white", "red", "yellow", "blue", "green", "orange"],
    "renderer_version": "1.0.0"
  },
  "not_before": null,
  "expires_at": null
}
```

## Artifact requirements

- The initial format is a paletted PNG with `Content-Type: image/png`.
- Its dimensions must match the configured fixed display profile.
- The agent downloads bytes, verifies SHA-256 against `artifact.sha256`, decodes the
  image, validates dimensions, then writes it atomically into its local spool.
- Artifact URLs return binary bytes; image data is never embedded as base64 in JSON.
- The renderer version, palette, display profile, and render settings are part of
  the server artifact cache identity.

## Host UI request

`POST /api/v1/displays/{display_id}/display-now` accepts `DisplayNowRequest`:

```json
{
  "asset_id": "9a595797-c181-4f53-8927-2a6fe776c65b",
  "render_settings": {
    "fit_mode": "crop",
    "dither_mode": "floyd-steinberg",
    "focal_point_x": 0.5,
    "focal_point_y": 0.5,
    "flip_horizontal": false,
    "flip_vertical": false
  }
}
```

Omitting `render_settings` uses the fixed profile defaults. The host renders first,
then atomically sets the produced artifact as the latest desired revision.

