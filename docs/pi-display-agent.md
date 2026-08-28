# Raspberry Pi Display Agent

## Purpose

The Raspberry Pi is a small, reliable hardware agent. It connects to the Docker host, downloads prepared display artifacts, and performs the physical update through the Pimoroni Inky library.

The Pi should not host the web interface, perform expensive image processing, or be the authoritative scheduler.

## Hardware target

The development hardware is a Raspberry Pi 4, but the deployment target is a Raspberry Pi Zero W.

The display target is the Pimoroni Inky Impression 7.3-inch Spectra 6 display:

- Driver: E673
- Resolution: 800 x 480 pixels
- Six display colours
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
- `httpx` for outbound HTTPS communication
- Python `sqlite3` for durable local state
- Pillow for decoding downloaded images
- `systemd` watchdog/restart handling
- `journald` for logs
- `venv` or a pinned application virtual environment
- Environment variables or a root-readable configuration file for server URL and device token

Avoid Docker on the Pi Zero W. It adds memory, storage, and operational overhead without helping the display workload.

## Agent responsibilities

1. Start at boot.
2. Identify the display using `inky.auto()` and EEPROM data where available.
3. Register the display and its capabilities with the server.
4. Send a heartbeat periodically.
5. Ask the server whether a newer revision is available.
6. Download the binary artifact over HTTPS.
7. Verify the artifact checksum and dimensions.
8. Store it atomically in a local spool directory.
9. Display it from one serialized hardware worker.
10. Report `started`, `completed`, or `failed` status.
11. Retry network operations with exponential backoff.
12. Continue using cached content when the server is unavailable.

The physical display operation must be protected by a lock. A new image must never be sent to the panel while a previous refresh is still active.

## Communication model

The Pi should initiate all connections to the Docker host. This avoids opening an inbound port on the Pi and works even if the Pi later moves behind a firewall or NAT.

The initial protocol should use HTTPS REST endpoints:

```text
GET  /api/v1/displays/{display_id}/desired
POST /api/v1/displays/{display_id}/register
GET  /api/v1/artifacts/{sha256}
POST /api/v1/displays/{display_id}/jobs/{job_id}/started
POST /api/v1/displays/{display_id}/jobs/{job_id}/completed
POST /api/v1/displays/{display_id}/jobs/{job_id}/failed
POST /api/v1/displays/{display_id}/heartbeat
```

Long polling or a short polling interval is sufficient for the first version. A WebSocket notification channel can be added later without changing artifact delivery.

Each device should have its own authentication token. The Pi must validate HTTPS certificates and must never log the token.

## Artifact format

The first implementation should use an 800 x 480 paletted PNG:

- Final dimensions are validated on the server and Pi.
- The server performs resize, crop/fit, colour conversion, and dithering.
- The Pi only decodes the image and performs the small final Inky buffer conversion.
- The artifact includes a SHA-256 checksum and renderer version in its metadata.

If Pillow/Inky processing is too slow on the Pi Zero W, add a second format later:

- Explicit six-colour palette
- Two four-bit pixel values per byte
- 192,000-byte packed payload
- Versioned header and checksum

The packed format should be implemented behind a tested adapter rather than depending on undocumented driver internals.

## Local state

Store the following in `/var/lib/inky-agent/`:

- Device identifier
- Last acknowledged server revision
- Last successfully displayed artifact checksum
- Current job status
- Cached current image
- Cached next image, if available
- Last successful heartbeat

Use temporary files followed by an atomic rename when writing artifacts. A corrupt or incomplete download must never replace the current cache.

## Failure behaviour

- Server unavailable: keep the current image and retry later.
- Download interrupted: resume or restart, then verify the checksum.
- Invalid artifact: reject it and report the failure.
- Pi rebooted: re-register and reconcile its revision with the server.
- Power loss during refresh: mark the result as uncertain and safely retry the desired revision after boot.
- Lost completion acknowledgement: permit the same revision to be delivered again; updates are at-least-once and revision-idempotent.

## Loop and schedule constraints

The E673 display performs slow full refreshes. Loops should normally use intervals of at least one or two minutes, subject to measurement on the target hardware.

The Pi may download the next image while the display is busy, but it must not start the next physical refresh until the current `show()` call has returned.

## Testing requirements

- Mock transport tests for registration, polling, retries, and checksum failures
- Local filesystem crash/atomic-write tests
- Inky mock tests for image submission
- Hardware smoke test on the Pi 4
- Hardware timing test on the Pi Zero W
- Power-loss/reboot test during and after a refresh
- Offline operation test with the server stopped
- Verification that only one display update can run at a time
