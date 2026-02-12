"""Google OAuth2 authentication manager — multi-account registry."""

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.config import settings

logger = logging.getLogger(__name__)


class GoogleAuthManager:
    """Per-account Google OAuth credentials and API service builder.

    Instances are cached by account name. Use ``get(account)`` to obtain
    the manager for a named account (or the default).
    """

    _instances: dict[str, "GoogleAuthManager"] = {}

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/contacts",
    ]

    def __init__(self, account: str, token_path: Path) -> None:
        self._account = account
        self._token_path = token_path
        self._credentials: Credentials | None = None

    @classmethod
    def get(cls, account: str | None = None) -> "GoogleAuthManager":
        """Return the manager for *account*, creating it lazily.

        When *account* is ``None``, the default account from settings is used.
        Raises ``ValueError`` if the account is not in ``GOOGLE_ACCOUNTS``.
        """
        configured = settings.get_google_accounts()
        if not configured:
            msg = (
                "GOOGLE_ACCOUNTS is not configured. "
                "Set it in .env (e.g. GOOGLE_ACCOUNTS=work,personal)."
            )
            raise ValueError(msg)

        name = account or settings.google_default_account
        if not name:
            name = configured[0]

        if name not in configured:
            msg = (
                f"Google account '{name}' is not in GOOGLE_ACCOUNTS "
                f"({', '.join(configured)})"
            )
            raise ValueError(msg)

        if name not in cls._instances:
            token_path = Path(f"auth_tokens/google_{name}_auth_token.json")
            cls._instances[name] = cls(name, token_path)

        return cls._instances[name]

    @classmethod
    def any_enabled(cls) -> bool:
        """True if any configured account has a token file on disk.

        Returns False (with a warning) when ``GOOGLE_ACCOUNTS`` is empty.
        """
        configured = settings.get_google_accounts()
        if not configured:
            logger.warning("GOOGLE_ACCOUNTS is not configured — Google tools disabled")
            return False
        return any(
            Path(f"auth_tokens/google_{name}_auth_token.json").exists() for name in configured
        )

    @property
    def enabled(self) -> bool:
        """True if this account's token file exists on disk."""
        return self._token_path.exists()

    # -- credential management ------------------------------------------------

    def _load_credentials(self) -> Credentials:
        """Load credentials from token file, refreshing if expired."""
        if not self._token_path.exists():
            msg = (
                f"Google token file not found at {self._token_path}. "
                f"Run `python scripts/google_auth.py --account {self._account}` "
                "to authenticate."
            )
            raise FileNotFoundError(msg)

        creds = Credentials.from_authorized_user_file(str(self._token_path), self.SCOPES)

        if creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Google credentials for account '%s'", self._account)
            creds.refresh(Request())
            self._token_path.write_text(creds.to_json(), encoding="utf-8")
            logger.info("Google credentials refreshed and saved for account '%s'", self._account)

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

    def people(self):  # noqa: ANN201
        """Build a People API service."""
        return build("people", "v1", credentials=self._get_credentials())
