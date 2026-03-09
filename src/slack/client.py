"""Slack message client using slack-sdk's AsyncWebClient."""

from __future__ import annotations

import logging

from src.integrations.slack_auth import SlackAuthManager

logger = logging.getLogger(__name__)

# Slack's message length limit (characters). Messages longer than this are truncated.
MAX_SLACK_LENGTH = 4000


async def send_slack_message(
    channel: str,
    text: str,
    *,
    workspace: str | None = None,
    thread_ts: str | None = None,
) -> bool:
    """Send a message via the Slack bot token. Returns True on success."""
    try:
        mgr = SlackAuthManager.get(workspace)
    except (ValueError, FileNotFoundError):
        logger.error("Slack not configured for workspace=%s", workspace)
        return False

    if len(text) > MAX_SLACK_LENGTH:
        text = text[: MAX_SLACK_LENGTH - 3] + "..."

    try:
        client = mgr.bot_client()
        await client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)
        logger.info("Slack message sent to %s (%d chars)", channel, len(text))
        return True
    except Exception:
        logger.exception("Slack message send failed: channel=%s", channel)
        return False
