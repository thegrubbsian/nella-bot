"""SMS implementation of the NotificationChannel protocol."""

from __future__ import annotations

import logging

from src.sms.client import send_sms

logger = logging.getLogger(__name__)


class SMSChannel:
    """Sends notifications via SMS (Telnyx)."""

    @property
    def name(self) -> str:
        return "sms"

    async def send(self, user_id: str, message: str) -> bool:
        """Send a plain text SMS."""
        return await send_sms(user_id, message)

    async def send_rich(
        self,
        user_id: str,
        message: str,
        *,
        buttons: list[list[dict[str, str]]] | None = None,
        parse_mode: str | None = None,
    ) -> bool:
        """Send a message, stripping rich formatting (SMS is plain text)."""
        # Ignore buttons and parse_mode — SMS can't render them
        return await self.send(user_id, message)

    async def send_photo(
        self,
        user_id: str,
        photo: bytes,
        *,
        caption: str | None = None,
    ) -> bool:
        """SMS can't send photos (MMS is a future enhancement)."""
        logger.warning("SMSChannel.send_photo not supported — SMS can't send photos")
        return False
