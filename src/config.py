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
    allowed_user_ids: str = Field(default="")

    # Anthropic
    anthropic_api_key: str = Field(default="")
    claude_model: str = Field(default="claude-sonnet-4-5-20250929")
    default_chat_model: str = Field(default="sonnet")
    default_memory_model: str = Field(default="haiku")

    # Google
    google_credentials_path: str = Field(default="credentials.json")
    google_token_path: str = Field(default="token.json")

    # Mem0
    mem0_api_key: str = Field(default="")

    # Database
    database_path: Path = Field(default=Path("data/nella.db"))

    # Conversation
    conversation_window_size: int = Field(default=50)

    # Memory extraction
    memory_extraction_enabled: bool = Field(default=True)
    memory_extraction_model: str = Field(default="claude-haiku-4-5-20251001")

    # Logging
    log_level: str = Field(default="INFO")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def get_allowed_user_ids(self) -> set[int]:
        """Parse ALLOWED_USER_IDS into a set of ints."""
        if not self.allowed_user_ids.strip():
            return set()
        return {int(uid.strip()) for uid in self.allowed_user_ids.split(",") if uid.strip()}


settings = Settings()
