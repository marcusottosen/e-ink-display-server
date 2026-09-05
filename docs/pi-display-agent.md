# Raspberry Pi Display Agent

## Purpose

The Raspberry Pi is a small, reliable hardware agent. It connects to the Docker host, downloads prepared display artifacts, and performs the physical update through the Pimoroni Inky library.

The Pi should not host the web interface, perform expensive image processing, or be the authoritative scheduler.

## Hardware target

The development hardware is a Raspberry Pi 4, but the deployment target is a Raspberry Pi Zero W.

The display target is the fixed Pimoroni Inky Impression E673 display:

- Driver: E673
- Resolution: 800 x 480 pixels
- Seven display colours: black, white, red, yellow, blue, green, and orange
- SPI for display data
- I²C for EEPROM/display identification
- GPIO busy, reset, and data/command signals
- Full refreshes are slow; the current driver has a roughly 32-second busy phase

The display driver currently uses these GPIOs:

| Function | GPIO |
| --- | ---: |
| SPI MOSI | 10 |
| SPI clock | 11 |
| Chip select | 8 |
| Data/command | 22 |
| Reset | 27 |
| Busy | 17 |

The exact hardware must be verified on the physical Pi/display combination.

Use the fixed Inky E673 driver directly: create
`inky.inky_e673.Inky(resolution=(800, 480))`, pass the unchanged downloaded
image to `set_image()`, then call `show()`. Do not use `inky.auto()` or detect,
register, or report display capabilities.

## Required software

- Raspberry Pi OS Bookworm or newer
- Python 3.11 or newer where available
- Pimoroni `inky` library
- Pillow
- NumPy
- `smbus2`
- `spidev`
- `gpiodevice`
- `httpx`
- Enabled SPI interface
- Enabled I²C interface
- `dtoverlay=spi0-0cs` when required by the board configuration
- `systemd` for service management
- Wi-Fi connectivity to the Docker host

The Inky library itself documents Python 3.7+ and the runtime dependencies. Python 3.11 is the preferred Pi application version because it is current on modern Raspberry Pi OS releases while remaining compatible with the library.

## Recommended agent technologies

- Python, kept as a single small service
- `httpx` for outbound HTTP communication to the configured Docker host
- Python `sqlite3` for durable local state
- Pillow for decoding downloaded images
- `systemd` watchdog/restart handling
- `journald` for logs
- `venv` or a pinned application virtual environment
- Environment variables or a root-readable configuration file for the server URL

Avoid Docker on the Pi Zero W. It adds memory, storage, and operational overhead without helping the display workload.

## Agent responsibilities

1. Start at boot.
2. Use the fixed E673 Inky driver.
3. Send a heartbeat periodically.
4. Ask the server whether a newer revision is available.
5. Download the binary artifact over HTTP.
6. Verify the artifact checksum and dimensions.
7. Store it atomically in a local spool directory.
8. Display it from one serialized hardware worker using `set_image()` and `show()`.
9. Report `started`, `completed`, or `failed` status.
10. Retry network operations with exponential backoff.
11. Continue using cached content when the server is unavailable.

The physical display operation must be protected by a lock. A new image must never be sent to the panel while a previous refresh is still active.

## Communication model

The Pi should initiate all connections to the Docker host. This avoids opening an inbound port on the Pi and works even if the Pi later moves behind a firewall or NAT.

The current protocol uses HTTP REST endpoints on the trusted home LAN:

```text
GET  /api/v1/displays/{display_id}/desired?current_revision={revision}
GET  /api/v1/artifacts/{sha256}
POST /api/v1/displays/{display_id}/jobs/{job_id}/started
POST /api/v1/displays/{display_id}/jobs/{job_id}/completed
POST /api/v1/displays/{display_id}/jobs/{job_id}/failed
POST /api/v1/displays/{display_id}/heartbeat
```

Long polling or a short polling interval is sufficient for the first version. A WebSocket notification channel can be added later without changing artifact delivery.

There is no registration endpoint. `204 No Content` from `desired` means no newer
image is available; `200 OK` contains the newest desired revision, job ID, and
artifact descriptor. The artifact URL in that descriptor is relative to the
configured server URL.

Heartbeat JSON requires `current_revision` (zero or higher) and UTC `sent_at`;
`last_successful_artifact_sha256` is optional. Job-report JSON requires an
`event` matching the URL (`started`, `completed`, or `failed`) and UTC
`occurred_at`. A `completed` report also includes `completed_revision`; a
`failed` report may include `error_code` and `error_message`.

## Artifact format

The host sends an 800 x 480 RGB PNG (`rgb-png`):

- Final dimensions are validated on the server and Pi.
- The server performs EXIF handling, user-selected rotation, crop/fit/stretch,
  and resize.
- The server deliberately does not apply palette conversion, dithering, or other
  colour changes.
- The Pi validates PNG/RGB/800 × 480 and passes it unchanged to the Inky driver.
- The artifact includes a SHA-256 checksum and renderer version in its metadata.

The Inky driver performs the unavoidable physical panel colour mapping during the
refresh. Do not implement a second packed artifact format for this project.

## Local state

Store the following in `/var/lib/inky-agent/`:

- Last successfully displayed server revision
- Last successfully displayed artifact checksum
- Pending `started`, `completed`, or `failed` acknowledgement
- Cached current image
- Last successful heartbeat

Use temporary files followed by an atomic rename when writing artifacts. A corrupt or incomplete download must never replace the current cache.

## Failure behaviour

- Server unavailable: keep the current image and retry later.
- Download interrupted: resume or restart, then verify the checksum.
- Invalid artifact: reject it and report the failure.
- Pi rebooted: load local state, retry any pending acknowledgement, and poll the
  desired endpoint with its saved revision.
- Power loss during refresh: mark the result as uncertain and safely retry the desired revision after boot.
- Lost completion acknowledgement: permit the same revision to be delivered again; updates are at-least-once and revision-idempotent.

## Loop and schedule constraints

The E673 display performs slow full refreshes. Loops should normally use intervals of at least one or two minutes, subject to measurement on the target hardware.

The Pi may download the next image while the display is busy, but it must not start the next physical refresh until the current `show()` call has returned.

## Testing requirements

- Mock transport tests for polling, retries, and checksum failures
- Local filesystem crash/atomic-write tests
- Inky mock tests for image submission
- Hardware smoke test on the Pi 4
- Hardware timing test on the Pi Zero W
- Power-loss/reboot test during and after a refresh
- Offline operation test with the server stopped
- Verification that only one display update can run at a time
