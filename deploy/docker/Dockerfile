# Docker-based development toolchain. Application images are added with their
# respective services in later phases.
FROM ghcr.io/astral-sh/uv:0.8.22-python3.12-bookworm@sha256:347a10b34f9dd5a8ebb6378bc5f3ba2c003ea7e53d4f51a99a01728197c495e4

WORKDIR /workspace

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/workspace/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["uv"]
CMD ["--version"]
