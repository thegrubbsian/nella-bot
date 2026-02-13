"""Nella bot entry point."""

import logging

from src.config import settings

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, settings.log_level),
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start the bot on the configured platform."""
    if settings.chat_platform == "slack":
        from src.bot.slack.app import run_slack

        logger.info("Starting Nella on Slack...")
        run_slack()
    else:
        from src.bot.telegram.app import create_app

        allowed = settings.get_allowed_user_ids()
        if not allowed:
            logger.warning("ALLOWED_USER_IDS is empty — bot will reject all messages")
        else:
            logger.info("Allowed user IDs: %s", allowed)

        logger.info("Starting Nella on Telegram with model %s...", settings.claude_model)
        app = create_app()
        app.run_polling()


if __name__ == "__main__":
    main()
