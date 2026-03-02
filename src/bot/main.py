"""Nella Telegram bot entry point."""

import logging

from src.bot.app import create_app
from src.config import settings

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, settings.log_level),
)

# Suppress noisy library loggers. httpx logs every Telegram polling
# request at INFO (~8,640/day), which overwhelms rsyslog/SolarWinds
# rate limits and drowns out actual application logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def main() -> None:
    """Start the bot."""
    allowed = settings.get_allowed_user_ids()
    if not allowed:
        logger.warning("ALLOWED_USER_IDS is empty — bot will reject all messages")
    else:
        logger.info("Allowed user IDs: %s", allowed)

    logger.info("Starting Nella with model %s...", settings.claude_model)
    app = create_app()
    app.run_polling()


if __name__ == "__main__":
    main()
