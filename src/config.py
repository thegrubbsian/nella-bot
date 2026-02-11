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
    google_accounts: str = Field(default="")
    google_default_account: str = Field(default="")
    plaud_google_account: str = Field(default="")

    # Mem0
    mem0_api_key: str = Field(default="")

    # Database
    database_path: Path = Field(default=Path("data/nella.db"))

    # Turso (hosted libSQL) — when set, overrides local database_path
    turso_database_url: str = Field(default="")
    turso_auth_token: str = Field(default="")

    # Conversation
    conversation_window_size: int = Field(default=50)

    # Memory extraction
    memory_extraction_enabled: bool = Field(default=True)
    memory_extraction_model: str = Field(default="claude-haiku-4-5-20251001")

    # Notifications
    default_notification_channel: str = Field(default="telegram")

    # Papertrail / SolarWinds Observability (log aggregation)
    papertrail_api_token: str = Field(default="")
    papertrail_api_url: str = Field(default="https://api.na-01.cloud.solarwinds.com")

    # Scheduler
    scheduler_timezone: str = Field(default="America/Chicago")

    # Webhooks
    webhook_port: int = Field(default=8443)
    webhook_secret: str = Field(default="")

    # Plaud
    plaud_drive_folder_id: str = Field(default="")

    # Logging
    log_level: str = Field(default="INFO")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def get_allowed_user_ids(self) -> set[int]:
        """Parse ALLOWED_USER_IDS into a set of ints."""
        if not self.allowed_user_ids.strip():
            return set()
        return {int(uid.strip()) for uid in self.allowed_user_ids.split(",") if uid.strip()}

    def get_google_accounts(self) -> list[str]:
        """Parse GOOGLE_ACCOUNTS into a list of account names."""
        if not self.google_accounts.strip():
            return []
        return [name.strip() for name in self.google_accounts.split(",") if name.strip()]


settings = Settings()
