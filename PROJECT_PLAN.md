# Inky Display System — Review and Implementation Plan

## Repository review

The project is currently specification-only. The two source documents define a sensible split:

- `docker-host.md`: authoritative API, storage, rendering, scheduling, job delivery, and operations service.
- `pi-display-agent.md`: small outbound-only Raspberry Pi service that downloads verified artifacts and serializes hardware refreshes.

The main architectural boundary is clear: image processing and desired-state decisions stay on the Docker host; the Pi remains a resilient hardware adapter with an offline cache. The first useful milestone should stay deliberately small: one display, one uploaded asset, deterministic 800×480 rendering, `display-now`, polling, acknowledgements, and recovery after disconnects.

Important decisions to preserve during implementation:

- Treat the server as the source of truth and use monotonic display revisions.
- Make delivery at-least-once and revision-idempotent; do not delete artifacts because an acknowledgement was lost.
- Keep artifact rendering deterministic and include source hash, profile, settings, and renderer version in the cache identity.
- Never process uploads or run display refreshes directly in request handlers.
- Use atomic writes on both server and Pi storage.
- Verify the E673 GPIO mapping and refresh timing on real hardware before calling the integration complete.

Open implementation risks are hardware/library compatibility on the Pi Zero W, the exact Inky palette and dithering behaviour, refresh duration, HTTPS certificate provisioning on a home LAN, and recovery semantics after power loss during `show()`.

## Target folder structure

```text
.
├── apps/
│   ├── host/                 # FastAPI application, models, API, rendering orchestration
│   └── pi-agent/             # Python hardware agent and local spool/state management
├── packages/
│   └── contract/             # Versioned API schemas and artifact contract documentation
├── deploy/
│   ├── docker/               # Compose files, Dockerfiles, and container configuration
│   └── systemd/              # Pi-agent service and watchdog configuration
├── tests/
│   ├── contract/             # Host/agent protocol compatibility tests
│   ├── host/                 # Rendering, API, worker, and schedule tests
│   └── pi-agent/             # Transport, cache, retry, and Inky mock tests
├── docs/                     # Architecture and operational documentation
├── scripts/                  # Explicit development, migration, and hardware utilities
├── .env.example              # Non-secret configuration reference
└── PROJECT_PLAN.md           # This review and task list
```

## To-do list

### Phase 0 — Foundations

- [ ] Add root project README, license decision, contribution notes, and `.gitignore`.
- [ ] Add Python dependency/tooling configuration with pinned or lockable dependencies.
- [ ] Define supported Python versions and development commands.
- [ ] Add `.env.example` with safe placeholders for host, database, Redis, and agent settings.
- [ ] Define the versioned API schemas and artifact metadata contract in `packages/contract/`.

### Phase 1 — Host vertical slice

- [ ] Scaffold the FastAPI host and health endpoint.
- [ ] Implement configuration and structured logging with correlation IDs.
- [ ] Implement asset upload validation, SHA-256 hashing, and persistent original storage.
- [ ] Implement deterministic Pillow rendering: EXIF orientation, crop/fit/padding, 800×480 resize, palette conversion, dithering, rotation/flip, preview, and paletted PNG artifact.
- [ ] Add renderer versioning and content-addressed artifact caching.
- [ ] Add one-display registration, capability storage, token hashing, heartbeat, and desired revision state.
- [ ] Implement `display-now`, desired-state lookup, binary artifact download, and job acknowledgements.
- [ ] Start with SQLite and a process-local worker for the single-display prototype; keep interfaces ready for PostgreSQL/Redis.

### Phase 2 — Pi agent vertical slice

- [ ] Scaffold the single-service Python agent and configuration loading without logging the device token.
- [ ] Implement `inky.auto()` identification and capability registration.
- [ ] Implement polling, heartbeat, HTTPS certificate validation, timeout handling, and exponential backoff.
- [ ] Implement checksum/dimension validation and crash-safe atomic artifact replacement in `/var/lib/inky-agent/`.
- [ ] Implement a single serialized hardware worker guarded by a lock.
- [ ] Implement `started`, `completed`, and `failed` reporting, including uncertain completion handling.
- [ ] Implement cached-image startup and offline operation.
- [ ] Add the systemd unit, restart policy, watchdog guidance, and Pi installation script.

### Phase 3 — Reliability and operations

- [ ] Add lease expiry, retry policy, stale-job collapse, and revision-idempotent reconciliation.
- [ ] Add schedule/playlist models with ordered items, durations, time zones, and start/end dates.
- [ ] Account for measured E673 refresh time when scheduling loops.
- [ ] Add PostgreSQL, Alembic migrations, Redis, and a dedicated worker when multi-display or durable queue requirements appear.
- [ ] Add Docker Compose services, persistent volumes, non-root containers where practical, health checks, and resource limits.
- [ ] Add display status dashboard data, metrics, structured audit history, and backup/restore procedures.

### Phase 4 — Verification and optimization

- [ ] Add unit tests for sizing, palette conversion, dithering, cache keys, checksums, and artifact corruption.
- [ ] Add API contract tests shared by host and agent.
- [ ] Add worker lease/retry and schedule/time-zone tests.
- [ ] Add filesystem crash/atomic-write and reboot/power-loss tests for the agent.
- [ ] Add Inky mock tests, Docker startup/health tests, and an end-to-end mock-display test.
- [ ] Run a Pi 4 smoke test and measure actual Pi Zero W download/decode/refresh timings.
- [ ] Verify GPIO, SPI, I²C, EEPROM identification, and E673 behaviour on the physical display.
- [ ] Decide whether the packed six-colour artifact format is justified; implement it only behind a tested adapter.

## Definition of done for the first milestone

One registered Pi can poll the host, receive a newer immutable 800×480 paletted PNG, verify its checksum, display it once through Inky, acknowledge the job, and recover to the latest desired revision after network loss or reboot. Uploads, artifacts, and local cache writes are durable and atomic, and the behaviour is covered by automated tests plus a real hardware smoke test.

