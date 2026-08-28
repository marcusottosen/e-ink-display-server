# Docker Host Display Control System

## Purpose

The Docker host is the brains of the system. It provides the web interface, stores uploaded content, prepares images for the target display, owns schedules and loops, and delivers immutable display jobs to Raspberry Pi agents.

The host should be the only side that performs expensive or extensible computation.

## Pi connection model

Use a **Pi-pull** connection: the Pi makes outbound HTTP requests to this host to
poll its desired revision, download an artifact, send a heartbeat, and acknowledge
the result. The host never opens a connection to the Pi.

This is the right model for the first appliance because it survives a Pi reboot,
Wi-Fi reconnect, changing Pi IP address, and ordinary home-network NAT without
discovery or inbound firewall rules. The only address to configure is the Docker
host's LAN URL and its published API port (normally `http://<host-lan-ip>:8000`).
The Pi needs no IP address or listening port in the host UI.

For the trusted-LAN prototype, plain HTTP and no agent authentication are
acceptable and are the defaults. Set `INKY_AGENT_AUTH_REQUIRED=true` and a unique
device token when the network is no longer fully trusted. HTTPS, stronger
authentication, and user accounts are explicitly deferred rather than being
half-implemented now.

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

## Frontend product requirements

The first frontend should be a focused control panel for one display, while keeping
the information model ready for multiple displays. The server owns a fixed display
profile for each configured agent; the Pi does not need to identify or report its
display model. The frontend must use the same renderer and display profile as
artifact delivery: a preview is a faithful representation of what will be sent to
the panel, not a browser-only approximation.

### Dashboard: upload and show

- Provide an `Upload and display` action as the primary path: select or drop one
  image, render it with the selected display settings, and make it the latest
  desired revision for the chosen display.
- For a single configured display, select it by default. For multiple displays,
  require a visible display selection before the action is submitted.
- Show rendering, download, refresh, completion, and failure status. A full E673
  refresh is slow, so the UI must set expectations rather than implying an
  immediate screen change.
- Keep the uploaded original and rendered artifact in the gallery. Do not make a
  one-off display action an ephemeral upload.
- Allow the user to review the faithful preview and adjust display settings before
  sending it; `Upload and display` may use the current defaults when no adjustment
  is needed.

### Display orientation and render settings

- Each configured display has a current physical orientation: landscape or portrait, with a
  corresponding 0°, 90°, 180°, or 270° rotation where the hardware installation
  requires it.
- The orientation is a display-level setting and is applied consistently to
  dashboard previews, gallery previews, album previews, render artifacts, and
  display actions. It must never silently change an original asset.
- Expose per-render framing controls: crop, fit, padding, focal point, rotation,
  and optional flip. Clearly distinguish these content settings from the physical
  display orientation.
- Preview the final 800 × 480 display raster at the configured orientation, with
  a visible indication of any crop or padding. Support both landscape and portrait
  installations.

### Gallery

- List all stored original images with thumbnail, filename, upload date, source
  dimensions, and the most recent rendered/displayed state.
- Allow opening an image to inspect its full seven-colour, display-resolution
  preview and to display it immediately using the current display settings.
- Support multi-select and bulk deletion as well as single-image deletion.
- Require confirmation for deletion and state whether an image is currently used
  by a running album or is the current display artifact. Preserve audit history and
  either prevent unsafe deletion or require an explicit replacement choice.
- Prefer a recoverable soft-delete/undo period before permanent storage cleanup.

### Albums

- Provide an album page to create, rename, reorder, and delete albums; add or
  remove existing gallery images; and inspect the rendered preview for each item.
- Each album has a `Run` action that makes the album the desired display program,
  plus `Stop`/replace behaviour that returns control to a single image or another
  album.
- Album settings include target display, sequential or shuffled order, interval,
  start image, enabled state, time zone, optional schedule, and the default
  framing/render settings for its items.
- Apply the display's physical orientation to every album preview and generated
  artifact. Per-image overrides should be possible later; album defaults are
  sufficient for the first album release.

### Future creative rendering

- Add a later, optional creative filter collection designed for the panel's
  seven-colour palette. These presets may deliberately stylize an image beyond
  accurate palette conversion.
- A filter selection must create a separately versioned render setting, show a
  faithful final-resolution preview before display, and never overwrite the
  original upload.

### Fitting supporting features

- Display status card: connection state, last heartbeat, current/desired revision,
  last successful refresh, and the latest error with a retry action where safe.
- Recent activity/history: who uploaded, rendered, displayed, ran, stopped, or
  deleted content, including job outcome and timestamps.
- Empty, loading, offline, and failed states designed for a household control
  panel, with clear recovery actions and no lost work after a refresh.

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
- Fixed display configuration and optional agent authentication
- Desired display revision management
- Playlists, loops, and schedules
- Job leases and retry handling
- Artifact delivery
- Display health/status dashboard
- Audit history for image and schedule changes
- Faithful, orientation-aware previews and frontend content management

The server is authoritative for the desired state. A display that is offline should receive the latest valid desired revision after reconnecting rather than an unbounded backlog of obsolete jobs.

## Rendering pipeline

For each requested display image:

1. Validate file type, file size, and image dimensions.
2. Normalize EXIF orientation and colour profile.
3. Apply the configured crop, fit, stretch, or padding mode.
4. Resize to 800 x 480.
5. Convert to the E673 seven-colour palette, including white.
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
- `agent_version`
- `last_seen_at`
- `last_error`
- `current_revision`
- `desired_revision`
- Server-configured resolution, palette, physical orientation, and rotation
- Server-configured default render/framing settings

### Assets

- `id`
- Original filename
- Original SHA-256
- Storage path
- MIME type
- File size
- Created timestamp
- Soft-deleted timestamp, when applicable
- Active-use deletion blockers for running albums, desired content, current content,
  and queued display work

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

### Albums, schedules, and playlists

- Display or display-group target
- Ordered items
- Sequential or shuffled order
- Per-item duration and default render settings
- Optional duration or cron-like schedule
- Time zone
- Enabled/disabled state
- Start/end dates
- Next item index and next scheduled run timestamp for an active album

### Activity history

- Event type and human-readable message
- Related display, asset, album, and job identifiers where applicable
- Timestamp

## API requirements

The API should expose versioned endpoints similar to:

```text
POST /api/v1/assets
GET  /api/v1/assets
DELETE /api/v1/assets/{asset_id}
POST /api/v1/assets/bulk-delete
POST /api/v1/assets/{asset_id}/restore
POST /api/v1/renders
GET  /api/v1/assets/{asset_id}/preview
POST /api/v1/albums
GET  /api/v1/albums
GET  /api/v1/albums/{album_id}
PATCH /api/v1/albums/{album_id}
PUT  /api/v1/albums/{album_id}/items
POST /api/v1/albums/{album_id}/run
POST /api/v1/albums/{album_id}/stop
DELETE /api/v1/albums/{album_id}
GET  /api/v1/activity
POST /api/v1/displays
GET  /api/v1/displays
GET  /api/v1/displays/{display_id}
PATCH /api/v1/displays/{display_id}/settings
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

## Gallery and album behaviour

Gallery deletion is a soft delete: original bytes and audit history remain available
for a later restore. The host rejects a single-image deletion when the asset is the
current or desired display content, is in a running album, or belongs to a queued,
rendering, ready, or active display job. A bulk-delete response reports protected
items while moving all safe selections to Trash.

An album has ordered gallery items, a display target, default render settings,
sequential or shuffle selection, a minimum 60-second interval, enabled state, time
zone, and optional start/end window. The prototype uses one serialized in-process
scheduler; it queues at most one new album item per interval and sends it through
the normal desired-state/render worker.

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

1. Define the versioned API, fixed display profile, and artifact contract.
2. Implement upload, storage, and deterministic rendering.
3. Configure the fixed single-display record and implement `display-now`.
4. Implement the Pi polling agent and acknowledgement flow.
5. Add status, retries, and offline caching.
6. Add playlists, loops, and time-zone-aware scheduling.
7. Add PostgreSQL/Redis separation and multiple-display support.
8. Benchmark the Pi Zero W and decide whether packed artifacts are necessary.
