"""Telegram implementation of the NotificationChannel protocol."""

from __future__ import annotations

import logging

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


class TelegramChannel:
    """Sends notifications via the Telegram Bot API."""

    def __init__(self, bot: telegram.Bot) -> None:
        self._bot = bot

    @property
    def name(self) -> str:
        return "telegram"

    async def send(self, user_id: str, message: str) -> bool:
        """Send a plain text message to a Telegram chat."""
        try:
            await self._bot.send_message(
                chat_id=int(user_id), text=message, parse_mode="Markdown"
            )
            return True
        except Exception:
            logger.exception("TelegramChannel.send failed for user_id=%s", user_id)
            return False

    async def send_rich(
        self,
        user_id: str,
        message: str,
        *,
        buttons: list[list[dict[str, str]]] | None = None,
        parse_mode: str | None = None,
    ) -> bool:
        """Send a message with optional inline keyboard buttons."""
        try:
            markup = None
            if buttons:
                markup = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            text=btn["text"],
                            callback_data=btn.get("callback_data"),
                            url=btn.get("url"),
                        )
                        for btn in row
                    ]
                    for row in buttons
                ])

            await self._bot.send_message(
                chat_id=int(user_id),
                text=message,
                parse_mode=parse_mode or "Markdown",
                reply_markup=markup,
            )
            return True
        except Exception:
            logger.exception(
                "TelegramChannel.send_rich failed for user_id=%s", user_id
            )
            return False

    async def send_photo(
        self,
        user_id: str,
        photo: bytes,
        *,
        caption: str | None = None,
    ) -> bool:
        """Send a photo to a Telegram chat."""
        try:
            await self._bot.send_photo(chat_id=int(user_id), photo=photo, caption=caption)
            return True
        except Exception:
            logger.exception("TelegramChannel.send_photo failed for user_id=%s", user_id)
            return False
