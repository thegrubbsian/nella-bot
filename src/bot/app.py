"""Telegram application factory."""

import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from src.bot.handlers import handle_clear, handle_message, handle_model, handle_start, handle_status
from src.config import settings
from src.notifications.router import NotificationRouter
from src.notifications.telegram_channel import TelegramChannel

logger = logging.getLogger(__name__)


def _init_notifications(app: Application) -> None:
    """Register notification channels and set the default."""
    router = NotificationRouter.get()
    telegram_channel = TelegramChannel(app.bot)
    router.register_channel(telegram_channel)
    router.set_default_channel(settings.default_notification_channel)
    logger.info(
        "Notifications initialized: channels=%s, default=%s",
        router.list_channels(),
        router.default_channel_name,
    )


def create_app() -> Application:
    """Build and configure the Telegram application."""
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    _init_notifications(app)

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("clear", handle_clear))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("model", handle_model))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    return app
