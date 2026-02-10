"""Lightweight async HTTP server for receiving webhooks.

Runs alongside the Telegram polling bot in the same asyncio event loop.
Uses aiohttp's AppRunner/TCPSite for non-blocking start/stop.

NOTE: The VPS firewall must allow inbound traffic on WEBHOOK_PORT
(default 8443). For UFW: ``sudo ufw allow 8443/tcp``
"""

from __future__ import annotations

import logging
import time
from typing import Any

from aiohttp import web

from src.config import settings
from src.webhooks.registry import webhook_registry

logger = logging.getLogger(__name__)


async def _handle_webhook(request: web.Request) -> web.Response:
    """Route POST /webhooks/<source> to the registered handler."""
    source = request.match_info["source"]

    # Validate shared secret
    secret = request.headers.get("X-Webhook-Secret", "")
    if not settings.webhook_secret or secret != settings.webhook_secret:
        logger.warning("Webhook rejected: invalid secret (source=%s)", source)
        return web.json_response({"error": "unauthorized"}, status=401)

    handler = webhook_registry.get(source)
    if handler is None:
        logger.warning("Webhook 404: no handler for source=%s", source)
        return web.json_response({"error": "unknown source"}, status=404)

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        logger.warning("Webhook bad request: invalid JSON (source=%s)", source)
        return web.json_response({"error": "invalid JSON"}, status=400)

    logger.info(
        "Webhook received: source=%s, time=%s, keys=%s",
        source,
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        list(payload.keys())[:10],
    )

    # Fire-and-forget: return 200 immediately, process in background.
    # Import here to avoid circular imports at module level.
    import asyncio

    asyncio.create_task(_run_handler(handler, source, payload))

    return web.json_response({"ok": True})


async def _run_handler(handler, source: str, payload: dict[str, Any]) -> None:
    """Execute a webhook handler with error logging."""
    try:
        await handler(payload)
    except Exception:
        logger.exception("Webhook handler failed: source=%s", source)


async def _health(request: web.Request) -> web.Response:
    """GET /health — basic liveness check."""
    return web.json_response({"status": "ok"})


def _create_web_app() -> web.Application:
    """Build the aiohttp Application with routes."""
    app = web.Application()
    app.router.add_get("/health", _health)
    app.router.add_post("/webhooks/{source}", _handle_webhook)
    return app


class WebhookServer:
    """Manages the aiohttp server lifecycle."""

    def __init__(self, port: int | None = None) -> None:
        self.port = port or settings.webhook_port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start listening for incoming webhooks."""
        if not settings.webhook_secret:
            logger.warning("WEBHOOK_SECRET is empty — webhook server disabled")
            return

        app = _create_web_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()
        logger.info(
            "Webhook server listening on port %d (sources: %s)",
            self.port,
            webhook_registry.sources or ["none registered"],
        )

    async def stop(self) -> None:
        """Shut down the server gracefully."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            logger.info("Webhook server stopped")
