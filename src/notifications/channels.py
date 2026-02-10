"""NotificationChannel protocol — interface for all notification delivery channels."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class NotificationChannel(Protocol):
    """Protocol that all notification channels must satisfy."""

    @property
    def name(self) -> str:
        """Unique channel identifier (e.g. 'telegram', 'sms')."""
        ...

    async def send(self, user_id: str, message: str) -> bool:
        """Send a plain text message. Returns True on success."""
        ...

    async def send_rich(
        self,
        user_id: str,
        message: str,
        *,
        buttons: list[list[dict[str, str]]] | None = None,
        parse_mode: str | None = None,
    ) -> bool:
        """Send a message with optional rich formatting. Returns True on success."""
        ...
