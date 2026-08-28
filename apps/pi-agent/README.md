# Inky Pi agent

The Pi agent is a single outbound-only service for the fixed 800 × 480 E673
display. It does not register, discover, or report a display model to the host.

The host creates an RGB PNG at the final dimensions and preserves original image
colours. The agent validates its checksum, format, mode, and dimensions before
atomically storing it in `/var/lib/inky-agent/artifacts/`. It never resizes a
download. The Inky hardware driver necessarily maps RGB pixels to the physical
panel's limited colours while refreshing the display.

## Configuration

Create `/etc/inky-agent/config.env` from
`deploy/systemd/inky-agent.env.example` and set the Docker host's LAN URL. The
only required network address is the host URL; the host does not need a Pi IP or
port. Device-token authentication is optional on a trusted LAN.

## Install on the Pi

Copy this repository to the Pi, then run:

```bash
sudo ./scripts/install-pi-agent.sh /path/to/inky
sudoedit /etc/inky-agent/config.env
sudo systemctl restart inky-agent
sudo systemctl status inky-agent
```

The installer enables SPI and I²C, installs the fixed E673 driver dependencies,
creates a restricted service account, and enables the systemd service. On
Raspberry Pi OS Bookworm, the Pi also needs `dtoverlay=spi0-0cs`; the installer
adds it when absent and reports that a reboot is required.
