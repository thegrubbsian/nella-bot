"""Telegram message handlers."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.config import settings
from src.llm.client import generate_response
from src.memory.store import save_message

logger = logging.getLogger(__name__)


def _is_owner(update: Update) -> bool:
    """Check if the message is from the bot owner."""
    return str(update.effective_chat.id) == settings.telegram_owner_chat_id


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    if not _is_owner(update):
        await update.message.reply_text("Sorry, I'm a personal assistant. I only talk to my owner.")
        return

    await update.message.reply_text(
        "Hey! I'm Nella, your personal assistant. What can I help you with?"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages."""
    if not _is_owner(update):
        return

    user_message = update.message.text
    chat_id = str(update.effective_chat.id)

    logger.info("Received message from owner: %s", user_message[:50])

    await save_message(chat_id=chat_id, role="user", content=user_message)

    response = await generate_response(user_message=user_message, chat_id=chat_id)

    await save_message(chat_id=chat_id, role="assistant", content=response)

    await update.message.reply_text(response)
