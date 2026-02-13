"""Systemd watchdog integration — zero external dependencies.

Sends sd_notify messages over the NOTIFY_SOCKET unix socket that systemd
provides.  When NOTIFY_SOCKET is absent (local dev, tests), all calls are
silent no-ops.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket

logger = logging.getLogger(__name__)

_WATCHDOG_INTERVAL_SECONDS = 15


def sd_notify(state: str) -> None:
    """Send a raw sd_notify message to systemd.

    Does nothing when NOTIFY_SOCKET is not set (i.e. outside systemd).
    """
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    # Abstract socket addresses start with @
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.connect(addr)
        sock.sendall(state.encode())
    except OSError:
        logger.warning("Failed to send sd_notify: %s", state)
    finally:
        sock.close()


def notify_ready() -> None:
    """Tell systemd the service is fully initialized."""
    sd_notify("READY=1")
    logger.info("Notified systemd: READY")


async def watchdog_loop() -> None:
    """Periodically ping the systemd watchdog.

    Runs forever as a background task.  If NOTIFY_SOCKET is absent this
    loop still runs but sd_notify() is a no-op.
    """
    while True:
        sd_notify("WATCHDOG=1")
        await asyncio.sleep(_WATCHDOG_INTERVAL_SECONDS)


def start_watchdog(loop: asyncio.AbstractEventLoop | None = None) -> asyncio.Task | None:
    """Spawn the watchdog loop as a fire-and-forget task.

    Returns the task (useful for testing) or None when not running under
    systemd.
    """
    if not os.environ.get("NOTIFY_SOCKET"):
        logger.debug("NOTIFY_SOCKET not set — watchdog disabled")
        return None
    task = asyncio.ensure_future(watchdog_loop())
    logger.info("Watchdog loop started (interval=%ds)", _WATCHDOG_INTERVAL_SECONDS)
    return task
