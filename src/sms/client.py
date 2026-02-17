"""Telnyx SMS API client using aiohttp."""

from __future__ import annotations

import logging

import aiohttp

from src.config import settings

logger = logging.getLogger(__name__)

# Maximum SMS body length (~10 segments). Longer messages risk delivery issues.
MAX_SMS_LENGTH = 1600

TELNYX_API_URL = "https://api.telnyx.com/v2/messages"

_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    """Return (and lazily create) the shared aiohttp session."""
    global _session  # noqa: PLW0603
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {settings.telnyx_api_key}"},
        )
    return _session


async def send_sms(to: str, body: str) -> bool:
    """Send an SMS via Telnyx. Returns True on success."""
    if not settings.telnyx_api_key or not settings.telnyx_phone_number:
        logger.error("SMS not configured — missing TELNYX_API_KEY or TELNYX_PHONE_NUMBER")
        return False

    # Truncate to avoid excessive segments / delivery failures
    if len(body) > MAX_SMS_LENGTH:
        body = body[: MAX_SMS_LENGTH - 3] + "..."

    payload = {
        "from": settings.telnyx_phone_number,
        "to": to,
        "text": body,
        "type": "SMS",
    }

    session = _get_session()
    try:
        async with session.post(TELNYX_API_URL, json=payload) as resp:
            if resp.status == 200:
                logger.info("SMS sent to %s (%d chars)", to, len(body))
                return True
            text = await resp.text()
            logger.error("SMS send failed: status=%d body=%s", resp.status, text[:200])
            return False
    except Exception:
        logger.exception("SMS send failed (network error)")
        return False
