# Inky home display

## Technologies

- Python 3.12, FastAPI, SQLAlchemy, Pydantic, Pillow
- SQLite for application data
- Vanilla HTML, CSS, and JavaScript for the web UI
- Docker Compose for the host
- Raspberry Pi OS, Pimoroni Inky, and systemd for the display agent

## Run the host

Requirements: Git, Docker Engine, and the Docker Compose plugin.

```bash
git clone <repository-url> inky
cd inky
cp .env.example .env
docker compose -f deploy/docker/compose.yaml up -d --build host
```

Open `http://<host-ip>:8000`. The host stores SQLite data, uploaded images, and
generated display files in the named Docker volume `inky-host-data`.

To update an existing checkout:

```bash
git pull
docker compose -f deploy/docker/compose.yaml up -d --build host
```

## Fresh Debian or Ubuntu host

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker
git clone <repository-url> inky
cd inky
cp .env.example .env
docker compose -f deploy/docker/compose.yaml up -d --build host
```

The web host listens on port `8000` by default. Set `INKY_HOST_PORT` in `.env`
to publish a different port.

## Pi agent

See [the Pi agent notes](docs/pi-display-agent.md) and
[the Docker host notes](docs/docker-host.md).
