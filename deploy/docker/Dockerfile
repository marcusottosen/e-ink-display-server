# Docker-based development toolchain and host image.
FROM ghcr.io/astral-sh/uv:0.8.22-python3.12-bookworm@sha256:347a10b34f9dd5a8ebb6378bc5f3ba2c003ea7e53d4f51a99a01728197c495e4 AS tools

WORKDIR /workspace

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/workspace/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["uv"]
CMD ["--version"]

FROM tools AS host

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/inky-venv \
    PATH="/opt/inky-venv/bin:$PATH"

COPY pyproject.toml uv.lock README.md ./
COPY apps ./apps
COPY packages ./packages
RUN uv sync --frozen --no-dev --package inky-host

EXPOSE 8000
ENTRYPOINT []
CMD ["uv", "run", "--no-sync", "--package", "inky-host", "uvicorn", "inky_host.main:app", "--host", "0.0.0.0", "--port", "8000"]
