"""User allowlist security gate."""

import logging

from telegram import Update

from src.config import settings

logger = logging.getLogger(__name__)

_allowed: set[int] | None = None


def _get_allowed() -> set[int]:
    """Lazily load and cache the allowed user IDs."""
    global _allowed  # noqa: PLW0603
    if _allowed is None:
        _allowed = settings.get_allowed_user_ids()
        logger.info("Allowed user IDs: %s", _allowed)
    return _allowed


def is_allowed(update: Update) -> bool:
    """Check if the update is from an allowed user.

    Returns False (silently rejected) for unknown users.
    """
    user = update.effective_user
    if user is None:
        return False

    allowed = _get_allowed()
    if not allowed:
        logger.warning("ALLOWED_USER_IDS is empty — rejecting all messages")
        return False

    return user.id in allowed
