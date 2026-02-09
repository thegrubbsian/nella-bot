"""Google OAuth2 authentication helper."""

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from src.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/tasks",
]


def get_google_credentials() -> Credentials:
    """Load or refresh Google OAuth2 credentials.

    On first run, opens a browser for OAuth consent. Subsequent runs
    use the cached token.
    """
    token_path = Path(settings.google_token_path)
    creds_path = Path(settings.google_credentials_path)

    creds: Credentials | None = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not creds_path.exists():
            msg = (
                f"Google credentials file not found at {creds_path}. "
                "Download it from Google Cloud Console."
            )
            raise FileNotFoundError(msg)

        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Google credentials saved to %s", token_path)

    return creds
