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


async def _handle_sms_inbound(request: web.Request) -> web.Response:
    """Handle inbound SMS from Telnyx."""
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)

    # Telnyx sends multiple event types — only process inbound messages
    event_type = payload.get("data", {}).get("event_type", "")
    if event_type != "message.received":
        return web.json_response({"ok": True})

    msg_payload = payload.get("data", {}).get("payload", {})
    from_number = msg_payload.get("from", {}).get("phone_number", "")
    text = msg_payload.get("text", "")

    if not from_number:
        logger.warning("SMS webhook: missing from phone number")
        return web.json_response({"ok": True})

    # Validate sender is the owner
    if from_number != settings.sms_owner_phone:
        logger.warning("SMS rejected: from=%s is not the owner", from_number)
        return web.json_response({"ok": True})

    import asyncio

    asyncio.create_task(_run_sms_handler(from_number, text))

    return web.json_response({"ok": True})


async def _run_sms_handler(from_number: str, text: str) -> None:
    """Execute the SMS handler with error logging."""
    try:
        from src.sms.handler import handle_inbound_sms

        await handle_inbound_sms(from_number, text)
    except Exception:
        logger.exception("SMS handler failed: from=%s", from_number)


def _create_web_app() -> web.Application:
    """Build the aiohttp Application with routes."""
    app = web.Application()
    app.router.add_get("/health", _health)
    app.router.add_post("/webhooks/{source}", _handle_webhook)

    # SMS inbound route (separate from webhook secret system)
    if settings.telnyx_api_key:
        app.router.add_post("/sms/inbound", _handle_sms_inbound)
        logger.info("SMS inbound route registered at /sms/inbound")

    return app


class WebhookServer:
    """Manages the aiohttp server lifecycle."""

    def __init__(self, port: int | None = None) -> None:
        self.port = port or settings.webhook_port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start listening for incoming webhooks and/or SMS."""
        sms_enabled = bool(settings.telnyx_api_key)

        if not settings.webhook_secret and not sms_enabled:
            logger.warning("WEBHOOK_SECRET empty and SMS not configured — server disabled")
            return

        # Import handlers so they register with the webhook_registry.
        if settings.webhook_secret:
            import src.webhooks.handlers  # noqa: F401

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
