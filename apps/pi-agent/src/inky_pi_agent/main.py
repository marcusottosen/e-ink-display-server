"""Command-line entry point for the Raspberry Pi display agent."""

from __future__ import annotations

import logging

from .agent import InkyAgent
from .config import AgentSettings
from .hardware import FixedE673Driver, NoopDisplayDriver, SerializedDisplayWorker
from .spool import AgentSpool
from .systemd import SystemdNotifier
from .transport import HostClient


def main() -> None:
    settings = AgentSettings()
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger = logging.getLogger(__name__)
    logger.info(
        "starting fixed E673 Pi agent",
        extra={
            "display_id": settings.display_id,
            "server_url": settings.base_url,
            "hardware_enabled": settings.hardware_enabled,
        },
    )
    driver = FixedE673Driver() if settings.hardware_enabled else NoopDisplayDriver()
    client = HostClient(settings)
    notifier = SystemdNotifier()
    notifier.ready()
    try:
        agent = InkyAgent(settings, client, AgentSpool(settings.data_dir), SerializedDisplayWorker(driver))
        agent.run_forever(notifier)
    finally:
        client.close()
