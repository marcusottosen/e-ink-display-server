# Docker Host Display Control System

## Purpose

The Docker host is the brains of the system. It provides the web interface, stores uploaded content, prepares images for the target display, owns schedules and loops, and delivers immutable display jobs to Raspberry Pi agents.

The host should be the only side that performs expensive or extensible computation.

## Recommended modern technology stack

### Backend

- Python 3.12 or newer
- FastAPI
- Pydantic v2 for request, response, and configuration models
- Uvicorn for local/container serving
- SQLAlchemy 2.x and Alembic for database access and migrations

### Frontend

- TypeScript
- SvelteKit or React with a small single-page interface
- Vite for frontend builds
- A component library or Tailwind CSS only if it improves delivery speed

The frontend can initially be served by the backend or a small separate web container.

### Storage and jobs

- PostgreSQL for durable application data
- Redis for job notifications, leases, and background work
- `arq`, Dramatiq, or an equivalent Redis-backed worker
- Persistent Docker volumes for originals, previews, and final artifacts

### Image processing

- Pillow as the primary renderer
- NumPy where useful for palette and pixel operations
- Optional ImageMagick/libvips only when a real feature requires it
- Content-addressed artifact storage using SHA-256

Avoid placing image-processing work inside request handlers.

## Docker deployment

The production deployment should be defined with Docker Compose and include:

- `web`: FastAPI and the frontend/static assets
- `worker`: image rendering and schedule/job processing
- `postgres`: durable database
- `redis`: queue/notification backend
- Optional reverse proxy such as Caddy or Traefik

Every stateful service must use a named or bind-mounted persistent volume. Container rebuilds must not delete uploads, schedules, display registrations, or job history.

Use multi-stage builds, pinned dependency lock files, non-root containers where practical, health checks, and explicit resource limits.

For a first single-display prototype, `web`, an in-process worker, SQLite, and local artifact storage are sufficient. PostgreSQL and Redis should be introduced when the service needs durable background workers, multiple displays, or higher operational reliability.

## Core server responsibilities

- User authentication and authorization
- Image upload and validation
- Original image storage
- Image rendering and preview generation
- Display registration and capability tracking
- Desired display revision management
- Playlists, loops, and schedules
- Job leases and retry handling
- Artifact delivery
- Display health/status dashboard
- Audit history for image and schedule changes

The server is authoritative for the desired state. A display that is offline should receive the latest valid desired revision after reconnecting rather than an unbounded backlog of obsolete jobs.

## Rendering pipeline

For each requested display image:

1. Validate file type, file size, and image dimensions.
2. Normalize EXIF orientation and colour profile.
3. Apply the configured crop, fit, stretch, or padding mode.
4. Resize to 800 x 480.
5. Convert to the E673 six-colour palette.
6. Apply the selected dithering strategy.
7. Apply rotation or flip settings if configured.
8. Produce a browser preview.
9. Produce the immutable device artifact.
10. Record renderer version, settings, dimensions, palette, and checksum.

The renderer should be deterministic. The artifact cache key should include the source image hash, display profile, render settings, and renderer version.

The first artifact format should be an 800 x 480 paletted PNG. A later optimized format may contain packed native pixel values for lower Pi CPU usage and predictable transfer size.

## Suggested data model

### Displays

- `id`
- `name`
- `device_token_hash`
- `model`
- `resolution`
- `palette`
- `agent_version`
- `last_seen_at`
- `last_error`
- `current_revision`
- `desired_revision`

### Assets

- `id`
- Original filename
- Original SHA-256
- Storage path
- MIME type
- File size
- Created timestamp

### Rendered artifacts

- Asset ID
- Display profile
- Renderer version
- Render settings
- Artifact format
- Width and height
- SHA-256
- Storage path

### Jobs

- `id`
- Display ID
- Artifact ID
- Revision
- Status
- Lease owner and expiry
- Created, started, completed, and failed timestamps
- Error information

### Schedules/playlists

- Display or display-group target
- Ordered items
- Duration or cron-like schedule
- Time zone
- Enabled/disabled state
- Start/end dates

## API requirements

The API should expose versioned endpoints similar to:

```text
POST /api/v1/assets
POST /api/v1/renders
GET  /api/v1/assets/{asset_id}/preview
POST /api/v1/displays
GET  /api/v1/displays
GET  /api/v1/displays/{display_id}
POST /api/v1/displays/{display_id}/register
POST /api/v1/displays/{display_id}/display-now
GET  /api/v1/displays/{display_id}/desired
GET  /api/v1/artifacts/{sha256}
POST /api/v1/displays/{display_id}/heartbeat
POST /api/v1/displays/{display_id}/jobs/{job_id}/started
POST /api/v1/displays/{display_id}/jobs/{job_id}/completed
POST /api/v1/displays/{display_id}/jobs/{job_id}/failed
```

The desired-state response should include:

- Job ID
- Monotonic revision
- Artifact URL
- SHA-256 checksum
- Artifact format
- Dimensions
- Border colour
- Renderer version
- Optional not-before and expiry timestamps

Artifact downloads must be binary responses, not base64 embedded in JSON.

## Queue and reliability rules

- Do not create a new physical update for every stale schedule tick.
- Collapse obsolete jobs for the same display.
- Use leases so abandoned jobs become available again.
- Use at-least-once delivery with revision-based idempotency.
- Do not mark a job complete until the Pi confirms that `show()` returned.
- Treat a lost acknowledgement as an uncertain result, not as permission to delete the artifact.
- Retain the latest artifact even after job history is cleaned up.

The server should account for the display refresh time when scheduling loops. It must not promise sub-minute visual changes on the E673 hardware.

## Security requirements

- HTTPS, including on the home LAN where practical
- One token per display, stored hashed on the server
- Password-protected web UI
- Input size/type validation for uploads
- No shell execution based on uploaded filenames or metadata
- Restricted artifact and upload paths
- Secrets supplied through environment variables or a secret manager
- Regular database and asset backups
- Firewall policy allowing the Pi to reach the server without exposing Pi services publicly

A static IP or DHCP reservation for the Docker host is recommended. The Pi should still use an outbound connection and should not require an inbound web port.

## Observability and operations

- Structured JSON logs
- Request, render, and display-job correlation IDs
- Health endpoints for web, database, Redis, and worker
- Metrics for render duration, queue depth, display duration, failures, and last heartbeat
- Error tracking such as Sentry or an equivalent self-hosted solution
- Database migrations run as an explicit deployment step
- Backup and restore procedure for PostgreSQL and asset volumes

## Testing requirements

- Unit tests for image sizing, palette conversion, dithering, and cache keys
- API contract tests shared with the Pi agent
- Worker retry and lease-expiry tests
- Artifact checksum and corruption tests
- Schedule/time-zone tests
- End-to-end test using an Inky mock
- Hardware integration test with a real E673 display
- Docker Compose startup and health-check test
- Backup restoration test

## Initial implementation order

1. Define the versioned API and artifact contract.
2. Implement upload, storage, and deterministic rendering.
3. Implement one-display registration and `display-now`.
4. Implement the Pi polling agent and acknowledgement flow.
5. Add status, retries, and offline caching.
6. Add playlists, loops, and time-zone-aware scheduling.
7. Add PostgreSQL/Redis separation and multiple-display support.
8. Benchmark the Pi Zero W and decide whether packed artifacts are necessary.
