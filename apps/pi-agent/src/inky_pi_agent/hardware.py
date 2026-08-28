"""Fixed E673 hardware adapter and a lock-protected refresh worker."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Protocol

from PIL import Image

EXPECTED_RESOLUTION = (800, 480)


class DisplayDriver(Protocol):
    def show(self, image_path: Path) -> None: ...


class FixedE673Driver:
    """Use the known E673 driver directly; no Pi-side detection is performed."""

    def __init__(self) -> None:
        try:
            from inky.inky_e673 import Inky  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError("Install the Pi agent with its 'hardware' extra to use the E673 display") from error
        self._display = Inky(resolution=EXPECTED_RESOLUTION)
        if self._display.resolution != EXPECTED_RESOLUTION:
            raise RuntimeError("configured E673 driver did not expose the expected 800x480 panel")

    def show(self, image_path: Path) -> None:
        with Image.open(image_path) as image:
            if image.size != EXPECTED_RESOLUTION:
                raise ValueError("Pi refuses to resize an artifact; the host must provide 800x480")
            self._display.set_image(image)
        self._display.show()


class NoopDisplayDriver:
    """Development-only driver that permits network/spool verification without GPIO."""

    def show(self, image_path: Path) -> None:
        if not image_path.is_file():
            raise FileNotFoundError(image_path)


class SerializedDisplayWorker:
    """Guarantee that at most one physical E-Ink update can run at a time."""

    def __init__(self, driver: DisplayDriver) -> None:
        self._driver = driver
        self._lock = threading.Lock()

    def refresh(self, image_path: Path) -> None:
        with self._lock:
            self._driver.show(image_path)
