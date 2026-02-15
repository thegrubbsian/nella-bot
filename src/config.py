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

    # Scratch space (local file storage for working files)
    scratch_dir: Path = Field(default=Path("data/scratch"))

    # Conversation
    conversation_window_size: int = Field(default=50)
    max_tool_rounds: int = Field(default=20)

    # Memory extraction
    memory_extraction_enabled: bool = Field(default=True)

    # Notifications
    default_notification_channel: str = Field(default="telegram")

    # Papertrail / SolarWinds Observability (log aggregation)
    papertrail_api_token: str = Field(default="")
    papertrail_api_url: str = Field(default="https://api.na-01.cloud.solarwinds.com")
    papertrail_ingestion_token: str = Field(default="")

    # Scheduler
    scheduler_timezone: str = Field(default="America/Chicago")

    # Webhooks
    webhook_port: int = Field(default=8443)
    webhook_secret: str = Field(default="")

    # ngrok
    ngrok_authtoken: str = Field(default="")
    ngrok_domain: str = Field(default="")

    # Brave Search (web research)
    brave_search_api_key: str = Field(default="")

    # GitHub
    github_token: str = Field(default="")
    nella_source_repo: str = Field(default="")

    # Browser automation (Playwright)
    browser_enabled: bool = Field(default=False)
    browser_model: str = Field(default="sonnet")
    browser_timeout_ms: int = Field(default=30000)
    browser_max_steps: int = Field(default=15)

    # LinkedIn
    linkedin_client_id: str = Field(default="")
    linkedin_client_secret: str = Field(default="")

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
