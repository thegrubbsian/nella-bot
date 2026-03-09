"""Lightweight async HTTP server for receiving webhooks.

Runs alongside the Telegram polling bot in the same asyncio event loop.
Uses aiohttp's AppRunner/TCPSite for non-blocking start/stop.

NOTE: The VPS firewall must allow inbound traffic on WEBHOOK_PORT
(default 8443). For UFW: ``sudo ufw allow 8443/tcp``
"""

from __future__ import annotations

import hashlib
import hmac
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


def _verify_slack_signature(
    body: bytes, timestamp: str, signature: str, signing_secret: str
) -> bool:
    """Verify Slack request signature (HMAC-SHA256)."""
    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _handle_slack_events(request: web.Request) -> web.Response:
    """Handle inbound Slack Events API requests."""
    try:
        raw_body = await request.read()
        payload: dict[str, Any] = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)

    # URL verification challenge (Slack sends this during app setup)
    if payload.get("type") == "url_verification":
        return web.json_response({"challenge": payload.get("challenge", "")})

    # Look up workspace by team_id
    team_id = payload.get("team_id", "")
    from src.integrations.slack_auth import SlackAuthManager

    mgr = SlackAuthManager.get_by_team_id(team_id)
    if mgr is None:
        logger.warning("Slack event rejected: unknown team_id=%s", team_id)
        return web.json_response({"error": "unknown team"}, status=403)

    # Verify signing secret
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if not _verify_slack_signature(raw_body, timestamp, signature, mgr.signing_secret):
        logger.warning("Slack event rejected: invalid signature (team=%s)", team_id)
        return web.json_response({"error": "invalid signature"}, status=401)

    # Process event_callback
    if payload.get("type") == "event_callback":
        event = payload.get("event", {})
        event_type = event.get("type", "")

        # Only handle direct messages (im)
        if event_type == "message" and event.get("channel_type") == "im":
            # Ignore message subtypes (edits, joins, bot_message, etc.)
            if event.get("subtype"):
                return web.json_response({"ok": True})

            # Ignore messages from the bot itself (prevent infinite loop)
            if event.get("user") == mgr.bot_user_id:
                return web.json_response({"ok": True})

            user_id = event.get("user", "")
            channel = event.get("channel", "")
            text = event.get("text", "")
            thread_ts = event.get("thread_ts")

            if user_id and channel and text:
                import asyncio

                asyncio.create_task(
                    _run_slack_handler(
                        mgr.workspace, user_id, channel, text, thread_ts
                    )
                )

    return web.json_response({"ok": True})


async def _run_slack_handler(
    workspace: str, user_id: str, channel: str, text: str, thread_ts: str | None
) -> None:
    """Execute the Slack handler with error logging."""
    try:
        from src.slack.handler import handle_inbound_slack_dm

        await handle_inbound_slack_dm(
            workspace, user_id, channel, text, thread_ts=thread_ts
        )
    except Exception:
        logger.exception("Slack handler failed: workspace=%s user=%s", workspace, user_id)


def _create_web_app() -> web.Application:
    """Build the aiohttp Application with routes."""
    app = web.Application()
    app.router.add_get("/health", _health)
    app.router.add_post("/webhooks/{source}", _handle_webhook)

    # SMS inbound route (separate from webhook secret system)
    if settings.telnyx_api_key:
        app.router.add_post("/sms/inbound", _handle_sms_inbound)
        logger.info("SMS inbound route registered at /sms/inbound")

    # Slack Events API route (separate from webhook secret system)
    from src.integrations.slack_auth import SlackAuthManager

    if SlackAuthManager.any_enabled():
        app.router.add_post("/slack/events", _handle_slack_events)
        logger.info("Slack events route registered at /slack/events")

    return app


class WebhookServer:
    """Manages the aiohttp server lifecycle."""

    def __init__(self, port: int | None = None) -> None:
        self.port = port or settings.webhook_port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start listening for incoming webhooks, SMS, and/or Slack events."""
        sms_enabled = bool(settings.telnyx_api_key)
        from src.integrations.slack_auth import SlackAuthManager

        slack_enabled = SlackAuthManager.any_enabled()

        if not settings.webhook_secret and not sms_enabled and not slack_enabled:
            logger.warning(
                "WEBHOOK_SECRET empty, SMS not configured, Slack not configured — server disabled"
            )
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
