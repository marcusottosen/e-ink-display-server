# Inky Display System

A self-hosted controller for a fixed Pimoroni Inky display. The Docker host stores
images, renders immutable display artifacts, provides the web UI, and owns desired
display state. The Raspberry Pi agent only polls the host and performs serialized
hardware refreshes.

## Current status

The host prototype is implemented through Phase 1.5: upload and deterministic
seven-colour rendering, display-now, gallery, albums, activity history, and a
browser UI. The Pi agent remains the next phase.

## Project layout

- `apps/host/` — future FastAPI host and frontend.
- `apps/pi-agent/` — future Raspberry Pi service.
- `packages/contract/` — shared Pydantic models and API/artifact contract.
- `deploy/docker/` — Docker-based development tooling.
- `deploy/systemd/` — future Pi service installation files.
- `tests/` — contract, host, and agent tests.

## Requirements

- Docker Engine with Docker Compose v2 or later.
- Python is optional on the host machine; Docker provides the supported toolchain.

Supported runtimes are Python 3.12–3.13 for the Docker host and Python 3.11–3.13
for the Pi agent. The Pi should use the Python version supplied by its supported
Raspberry Pi OS release.

## Start development with Docker

Create a local configuration file, then install the workspace dependencies inside
the Docker tooling container:

```bash
cp .env.example .env
docker compose -f deploy/docker/compose.yaml run --rm tools sync --all-packages --group dev
docker compose -f deploy/docker/compose.yaml run --rm tools run --package inky-host pytest tests/contract tests/host
```

The dependency resolver writes `uv.lock` at the repository root. Commit that file
whenever dependencies are changed; subsequent commands should use `--locked`.

Validate the Compose configuration without starting any service:

```bash
docker compose -f deploy/docker/compose.yaml --env-file .env config
```

The development container mounts the repository and keeps its virtual environment
in the named `inky-python-venv` volume, so Python dependencies do not pollute the
LXC.

## Run the host

Start the single-display host with a persistent Docker volume:

```bash
docker compose -f deploy/docker/compose.yaml up -d --build host
```

Open `http://<host>:8000` for the dashboard and `http://<host>:8000/health` for
the health check. The host stores SQLite state, uploads, previews, and artifacts in
the named `inky-host-data` volume. The Pi will poll this host; it needs the host's
LAN address and published port, while the host does not need a Pi IP or port.

## Fixed display configuration

The server is configured for a fixed display profile in its host settings. It
defines the 800 × 480, seven-colour target and its default physical orientation.
The Pi does not discover or report display model/capabilities to the server.
Physical orientation and rotation are persisted through the Settings page.

## Contract

The v1 API and artifact rules are documented in
[`packages/contract/README.md`](packages/contract/README.md). Shared validation
models live alongside it and are the only place where cross-service payloads should
be defined.

## License

This repository is currently source-available for its owner only. All rights are
reserved until an explicit open-source license is chosen.
