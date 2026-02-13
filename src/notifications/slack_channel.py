"""Slack implementation of the NotificationChannel protocol."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


class SlackChannel:
    """Sends notifications via the Slack API."""

    def __init__(self, client: AsyncWebClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "slack"

    async def _open_dm(self, user_id: str) -> str | None:
        """Open (or retrieve) a DM channel with a user. Returns channel ID."""
        try:
            resp = await self._client.conversations_open(users=[user_id])
            return resp["channel"]["id"]
        except Exception:
            logger.exception("SlackChannel: failed to open DM for user_id=%s", user_id)
            return None

    async def send(self, user_id: str, message: str) -> bool:
        """Send a plain text message to a Slack user via DM."""
        channel_id = await self._open_dm(user_id)
        if not channel_id:
            return False
        try:
            await self._client.chat_postMessage(channel=channel_id, text=message)
            return True
        except Exception:
            logger.exception("SlackChannel.send failed for user_id=%s", user_id)
            return False

    async def send_rich(
        self,
        user_id: str,
        message: str,
        *,
        buttons: list[list[dict[str, str]]] | None = None,
        parse_mode: str | None = None,
    ) -> bool:
        """Send a message with optional Block Kit buttons."""
        channel_id = await self._open_dm(user_id)
        if not channel_id:
            return False
        try:
            kwargs: dict[str, Any] = {"channel": channel_id, "text": message}
            if buttons:
                elements = []
                for row in buttons:
                    for btn in row:
                        elements.append({
                            "type": "button",
                            "text": {"type": "plain_text", "text": btn["text"]},
                            "action_id": btn.get("callback_data", btn["text"]),
                            "value": btn.get("callback_data", ""),
                        })
                kwargs["blocks"] = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": message}},
                    {"type": "actions", "elements": elements},
                ]
            await self._client.chat_postMessage(**kwargs)
            return True
        except Exception:
            logger.exception("SlackChannel.send_rich failed for user_id=%s", user_id)
            return False
