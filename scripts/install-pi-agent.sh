#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo $0 /path/to/inky" >&2
  exit 1
fi

source_dir=${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
install_dir=/opt/inky-agent/app
venv_dir=/opt/inky-agent/venv
config_dir=/etc/inky-agent

for required in "$source_dir/pyproject.toml" "$source_dir/apps/pi-agent" "$source_dir/packages/contract"; do
  if [[ ! -e $required ]]; then
    echo "Expected Inky source file or directory is missing: $required" >&2
    exit 1
  fi
done

apt-get update
apt-get install -y --no-install-recommends \
  build-essential i2c-tools libgpiod-dev python3-dev python3-venv
raspi-config nonint do_i2c 0
raspi-config nonint do_spi 0

boot_config=/boot/firmware/config.txt
if [[ -f /boot/config.txt ]]; then
  boot_config=/boot/config.txt
fi
if ! grep -qxF 'dtoverlay=spi0-0cs' "$boot_config"; then
  printf '\ndtoverlay=spi0-0cs\n' >>"$boot_config"
  echo "Added dtoverlay=spi0-0cs to $boot_config; reboot before first physical refresh."
fi

if ! id -u inky >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/inky-agent --groups spi,i2c,gpio inky
fi

install -d -m 0755 /opt/inky-agent
install -d -m 0755 "$install_dir"
cp -a "$source_dir/apps" "$source_dir/deploy" "$source_dir/packages" "$source_dir/pyproject.toml" "$install_dir/"

python3 -m venv "$venv_dir"
"$venv_dir/bin/pip" install --upgrade pip
"$venv_dir/bin/pip" install "$install_dir/packages/contract" "$install_dir/apps/pi-agent[hardware]"

install -d -m 0750 -o root -g inky "$config_dir"
if [[ ! -f "$config_dir/config.env" ]]; then
  install -m 0640 -o root -g inky "$install_dir/deploy/systemd/inky-agent.env.example" "$config_dir/config.env"
  echo "Edit $config_dir/config.env to set INKY_AGENT_SERVER_URL before starting the service."
fi
install -m 0644 "$install_dir/deploy/systemd/inky-agent.service" /etc/systemd/system/inky-agent.service
systemctl daemon-reload
systemctl enable inky-agent.service

echo "Installed Inky Pi agent. Reboot if the SPI overlay was added, then run: systemctl start inky-agent"
