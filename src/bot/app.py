"""Telegram application factory."""

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from src.bot.handlers import handle_clear, handle_message, handle_model, handle_start, handle_status
from src.config import settings


def create_app() -> Application:
    """Build and configure the Telegram application."""
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("clear", handle_clear))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("model", handle_model))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    return app
