"""NotificationRouter — singleton that dispatches messages to registered channels."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.notifications.channels import NotificationChannel

logger = logging.getLogger(__name__)


class NotificationRouter:
    """Routes outbound notifications to the appropriate channel.

    Singleton accessed via ``NotificationRouter.get()``.
    """

    _instance: NotificationRouter | None = None

    def __init__(self) -> None:
        self._channels: dict[str, NotificationChannel] = {}
        self._default: str = ""

    @classmethod
    def get(cls) -> NotificationRouter:
        """Return the singleton instance, creating it if needed."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        """Reset singleton — for tests only."""
        cls._instance = None

    def register_channel(self, channel: NotificationChannel) -> None:
        """Register a notification channel. Raises ValueError on duplicate name."""
        if channel.name in self._channels:
            msg = f"Channel '{channel.name}' is already registered"
            raise ValueError(msg)
        self._channels[channel.name] = channel

    def set_default_channel(self, name: str) -> None:
        """Set the default channel by name. Raises KeyError if not registered."""
        if name not in self._channels:
            msg = f"Channel '{name}' is not registered"
            raise KeyError(msg)
        self._default = name

    def get_channel(self, name: str) -> NotificationChannel | None:
        """Look up a channel by name."""
        return self._channels.get(name)

    def list_channels(self) -> list[str]:
        """Return names of all registered channels."""
        return list(self._channels.keys())

    @property
    def default_channel_name(self) -> str:
        """The name of the current default channel."""
        return self._default

    def _resolve_channel(self, name: str | None) -> NotificationChannel | None:
        """Resolve a channel: explicit name → default → only registered channel."""
        if name:
            return self._channels.get(name)
        if self._default:
            return self._channels.get(self._default)
        if len(self._channels) == 1:
            return next(iter(self._channels.values()))
        return None

    async def send(
        self,
        user_id: str,
        message: str,
        *,
        channel: str | None = None,
    ) -> bool:
        """Send a plain text message via the resolved channel."""
        ch = self._resolve_channel(channel)
        if ch is None:
            logger.warning("No channel resolved for send (requested=%s)", channel)
            return False
        return await ch.send(user_id, message)

    async def send_rich(
        self,
        user_id: str,
        message: str,
        *,
        channel: str | None = None,
        buttons: list[list[dict[str, str]]] | None = None,
        parse_mode: str | None = None,
    ) -> bool:
        """Send a rich message via the resolved channel."""
        ch = self._resolve_channel(channel)
        if ch is None:
            logger.warning("No channel resolved for send_rich (requested=%s)", channel)
            return False
        return await ch.send_rich(
            user_id, message, buttons=buttons, parse_mode=parse_mode
        )

    async def send_photo(
        self,
        user_id: str,
        photo: bytes,
        *,
        channel: str | None = None,
        caption: str | None = None,
    ) -> bool:
        """Send a photo via the resolved channel."""
        ch = self._resolve_channel(channel)
        if ch is None:
            logger.warning("No channel resolved for send_photo (requested=%s)", channel)
            return False
        return await ch.send_photo(user_id, photo, caption=caption)
