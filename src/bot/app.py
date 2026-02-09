"""Telegram application factory."""

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from src.bot.handlers import handle_message, handle_start
from src.config import settings


def create_app() -> Application:
    """Build and configure the Telegram application."""
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    return app
