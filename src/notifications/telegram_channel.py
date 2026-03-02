"""Telegram implementation of the NotificationChannel protocol."""

from __future__ import annotations

import logging

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.notifications.chunking import split_message

logger = logging.getLogger(__name__)


class TelegramChannel:
    """Sends notifications via the Telegram Bot API."""

    def __init__(self, bot: telegram.Bot) -> None:
        self._bot = bot

    @property
    def name(self) -> str:
        return "telegram"

    async def send(self, user_id: str, message: str) -> bool:
        """Send a plain text message to a Telegram chat.

        Long messages are automatically split at logical boundaries
        (paragraphs, headers, sentences) to stay within Telegram's
        4,096-character limit.
        """
        try:
            for chunk in split_message(message):
                await self._bot.send_message(
                    chat_id=int(user_id), text=chunk, parse_mode="Markdown"
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
        """Send a message with optional inline keyboard buttons.

        For multi-chunk messages, buttons are attached only to the final
        chunk so the conversation reads naturally.
        """
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

            chunks = split_message(message)
            mode = parse_mode or "Markdown"

            # Send leading chunks without buttons
            for chunk in chunks[:-1]:
                await self._bot.send_message(
                    chat_id=int(user_id),
                    text=chunk,
                    parse_mode=mode,
                )

            # Final chunk gets the reply_markup (buttons)
            await self._bot.send_message(
                chat_id=int(user_id),
                text=chunks[-1],
                parse_mode=mode,
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
