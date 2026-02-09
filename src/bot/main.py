"""Nella Telegram bot entry point."""

import logging

from dotenv import load_dotenv

from src.bot.app import create_app
from src.config import settings

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, settings.log_level),
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start the bot."""
    logger.info("Starting Nella...")
    app = create_app()
    app.run_polling()


if __name__ == "__main__":
    main()
