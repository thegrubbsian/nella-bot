"""Application settings loaded from environment variables."""

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    """Nella configuration. All values come from environment variables."""

    # Telegram
    telegram_bot_token: str = Field(default="")
    telegram_owner_chat_id: str = Field(default="")

    # Anthropic
    anthropic_api_key: str = Field(default="")
    claude_model: str = Field(default="claude-sonnet-4-20250514")

    # Google
    google_credentials_path: str = Field(default="credentials.json")
    google_token_path: str = Field(default="token.json")

    # Mem0
    mem0_api_key: str = Field(default="")

    # Database
    database_path: Path = Field(default=Path("data/nella.db"))

    # Logging
    log_level: str = Field(default="INFO")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
