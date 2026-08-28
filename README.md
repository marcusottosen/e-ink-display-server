# Inky home display tool

A small web tool for choosing images and sending them to one fixed Pimoroni Inky
display at home.

The Docker host provides the web pages, stores images, prepares the 800 × 480
PNG used by the panel, and keeps the latest requested image. The Raspberry Pi
asks the host for work and refreshes the display. The host does not connect to
the Pi.

## Run it

```bash
cp .env.example .env
docker compose -f deploy/docker/compose.yaml up -d --build host
```

Open `http://<host-lan-ip>:8000`.

Set the host LAN address and port in the Settings page before configuring the
Pi. The Pi only needs that host address; no Pi IP address or open Pi port is
needed in this tool.

## Storage

SQLite, original images, and generated display files are stored in Docker's
named `inky-host-data` volume. Container and LXC restarts do not remove it.
It is removed only if the Docker volume is explicitly removed or an LXC snapshot
is rolled back.

Deleting an image in the gallery permanently deletes that image and its generated
files. There is no Trash.

## What it does

- Upload an image, frame it, rotate it, and either save it or send it to the display.
- Keep a gallery of saved images, with per-image framing and rotation settings.
- Create albums and run them in order or shuffled, using a chosen interval.
- Play selected gallery images once as a temporary album without saving one.
- Sending one image to the display stops any running album.
- Show the image last confirmed by the Pi separately from the newest image the Pi can request.
- Let the Pi keep its last downloaded display file when the host is unavailable.

The host only rotates, frames, and resizes images. Colours are left alone.

## Layout

- `apps/host/` — FastAPI host and web UI.
- `apps/pi-agent/` — Pi service that polls the host and refreshes the panel.
- `packages/contract/` — shared host/Pi request models.
- `deploy/docker/` — Docker configuration for the host.
- `deploy/systemd/` — Pi service installation files.

## Pi setup

Copy this repository to the Pi and follow
[the Pi agent notes](apps/pi-agent/README.md).

## License

Private home-use repository. All rights reserved.
