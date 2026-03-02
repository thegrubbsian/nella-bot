"""Notification channel abstraction layer."""

from src.notifications.channels import NotificationChannel
from src.notifications.chunking import split_message
from src.notifications.context import MessageContext
from src.notifications.router import NotificationRouter
from src.notifications.telegram_channel import TelegramChannel

__all__ = [
    "MessageContext",
    "NotificationChannel",
    "NotificationRouter",
    "TelegramChannel",
    "split_message",
]
