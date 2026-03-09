"""Slack implementation of the NotificationChannel protocol."""

from __future__ import annotations

import logging

from src.notifications.chunking import split_message
from src.slack.client import MAX_SLACK_LENGTH, send_slack_message

logger = logging.getLogger(__name__)


class SlackChannel:
    """Sends notifications via Slack (bot token, default workspace)."""

    @property
    def name(self) -> str:
        return "slack"

    async def send(self, user_id: str, message: str) -> bool:
        """Send a plain text message to a Slack channel/DM.

        Long messages are automatically split at logical boundaries
        to stay within Slack's 4,000-character limit.
        """
        try:
            for chunk in split_message(message, max_length=MAX_SLACK_LENGTH):
                ok = await send_slack_message(user_id, chunk)
                if not ok:
                    return False
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
        """Send a message, ignoring rich formatting (Slack doesn't use Telegram keyboards)."""
        return await self.send(user_id, message)

    async def send_photo(
        self,
        user_id: str,
        photo: bytes,
        *,
        caption: str | None = None,
    ) -> bool:
        """Upload a photo to a Slack channel/DM."""
        try:
            from src.integrations.slack_auth import SlackAuthManager

            client = SlackAuthManager.get().bot_client()
            await client.files_upload_v2(
                channel=user_id,
                content=photo,
                filename="image.png",
                initial_comment=caption or "",
            )
            return True
        except Exception:
            logger.exception("SlackChannel.send_photo failed for user_id=%s", user_id)
            return False
