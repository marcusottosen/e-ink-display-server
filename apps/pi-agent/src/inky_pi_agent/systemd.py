"""Minimal systemd notification support without another runtime dependency."""

from __future__ import annotations

import os
import socket


class SystemdNotifier:
    def __init__(self) -> None:
        self._address = os.environ.get("NOTIFY_SOCKET")

    def ready(self) -> None:
        self._send("READY=1")

    def watchdog(self) -> None:
        self._send("WATCHDOG=1")

    def _send(self, message: str) -> None:
        if not self._address:
            return
        address = "\0" + self._address[1:] if self._address.startswith("@") else self._address
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            try:
                client.connect(address)
                client.sendall(message.encode())
            except OSError:
                # systemd notification must never stop display recovery.
                return
