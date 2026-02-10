"""Google OAuth2 authentication manager — singleton."""

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.config import settings

logger = logging.getLogger(__name__)


class GoogleAuthManager:
    """Singleton that owns Google OAuth credentials and builds API services."""

    _instance: "GoogleAuthManager | None" = None

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/documents",
    ]

    def __init__(self) -> None:
        self._credentials: Credentials | None = None

    @classmethod
    def get(cls) -> "GoogleAuthManager":
        """Return the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def enabled(self) -> bool:
        """True if a token file exists on disk."""
        return Path(settings.google_token_path).exists()

    # -- credential management ------------------------------------------------

    def _load_credentials(self) -> Credentials:
        """Load credentials from token file, refreshing if expired."""
        token_path = Path(settings.google_token_path)
        if not token_path.exists():
            msg = (
                f"Google token file not found at {token_path}. "
                "Run `python scripts/google_auth.py` to authenticate."
            )
            raise FileNotFoundError(msg)

        creds = Credentials.from_authorized_user_file(str(token_path), self.SCOPES)

        if creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Google credentials")
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
            logger.info("Google credentials refreshed and saved")

        return creds

    def _get_credentials(self) -> Credentials:
        """Return cached credentials, loading/refreshing as needed."""
        if self._credentials is None or (
            self._credentials.expired and self._credentials.refresh_token
        ):
            self._credentials = self._load_credentials()
        return self._credentials

    # -- service builders -----------------------------------------------------

    def gmail(self):  # noqa: ANN201
        """Build a Gmail API service."""
        return build("gmail", "v1", credentials=self._get_credentials())

    def calendar(self):  # noqa: ANN201
        """Build a Calendar API service."""
        return build("calendar", "v3", credentials=self._get_credentials())

    def drive(self):  # noqa: ANN201
        """Build a Drive API service."""
        return build("drive", "v3", credentials=self._get_credentials())

    def docs(self):  # noqa: ANN201
        """Build a Docs API service."""
        return build("docs", "v1", credentials=self._get_credentials())
