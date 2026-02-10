"""Webhook handler registry — central catalog for incoming webhook sources."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# Handler signature: async (payload: dict) -> None
WebhookHandler = Callable[[dict[str, Any]], Awaitable[None]]


class WebhookRegistry:
    """Registry for named webhook handlers.

    Usage::

        registry = WebhookRegistry()

        @registry.handler("plaud")
        async def handle_plaud(payload: dict) -> None:
            ...
    """

    def __init__(self) -> None:
        self._handlers: dict[str, WebhookHandler] = {}

    def handler(self, source: str) -> Callable[[WebhookHandler], WebhookHandler]:
        """Decorator to register an async function as a webhook handler."""

        def decorator(fn: WebhookHandler) -> WebhookHandler:
            self._handlers[source] = fn
            logger.info("Registered webhook handler: %s", source)
            return fn

        return decorator

    def get(self, source: str) -> WebhookHandler | None:
        """Look up a handler by source name."""
        return self._handlers.get(source)

    @property
    def sources(self) -> list[str]:
        """All registered source names."""
        return list(self._handlers)


webhook_registry = WebhookRegistry()
