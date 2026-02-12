"""LinkedIn OAuth2 authentication manager — single-account singleton."""

import json
import logging
import time
from pathlib import Path

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

TOKEN_PATH = Path("linkedin_token.json")
TOKEN_ENDPOINT = "https://www.linkedin.com/oauth/v2/accessToken"


class LinkedInAuthError(Exception):
    """Raised when LinkedIn authentication fails."""


class LinkedInAuth:
    """Single-account LinkedIn auth manager.

    Loads ``linkedin_token.json``, refreshes if possible, and provides
    headers for LinkedIn REST API calls.
    """

    _instance: "LinkedInAuth | None" = None

    def __init__(self) -> None:
        self._token_data: dict | None = None

    @classmethod
    def get(cls) -> "LinkedInAuth":
        """Return the singleton instance, creating it lazily."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def enabled(cls) -> bool:
        """True if the LinkedIn token file exists on disk."""
        return TOKEN_PATH.exists()

    @classmethod
    def reset(cls) -> None:
        """Clear the singleton (for testing)."""
        cls._instance = None

    def _load_token(self) -> dict:
        """Load token data from disk."""
        if not TOKEN_PATH.exists():
            msg = (
                "LinkedIn token file not found. "
                "Run `python scripts/linkedin_auth.py` to authenticate."
            )
            raise LinkedInAuthError(msg)
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))

    def _refresh(self, refresh_token: str) -> dict:
        """Exchange a refresh token for a new access token (sync)."""
        resp = httpx.post(
            TOKEN_ENDPOINT,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.linkedin_client_id,
                "client_secret": settings.linkedin_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if resp.status_code != 200:
            msg = f"LinkedIn token refresh failed ({resp.status_code}): {resp.text[:200]}"
            raise LinkedInAuthError(msg)
        return resp.json()

    def _ensure_token(self) -> dict:
        """Load token, refreshing if expired and a refresh_token exists."""
        if self._token_data is None:
            self._token_data = self._load_token()

        expires_at = self._token_data.get("expires_at", 0)
        if time.time() < expires_at:
            return self._token_data

        # Token expired — try refresh
        refresh_token = self._token_data.get("refresh_token", "")
        if not refresh_token:
            msg = (
                "LinkedIn access token has expired and no refresh token is available. "
                "Re-run `python scripts/linkedin_auth.py` to re-authenticate."
            )
            raise LinkedInAuthError(msg)

        logger.info("Refreshing expired LinkedIn access token")
        new_data = self._refresh(refresh_token)

        # Merge new token data
        self._token_data["access_token"] = new_data["access_token"]
        self._token_data["expires_at"] = time.time() + new_data.get("expires_in", 5184000)
        if new_data.get("refresh_token"):
            self._token_data["refresh_token"] = new_data["refresh_token"]

        # Persist updated token
        TOKEN_PATH.write_text(json.dumps(self._token_data, indent=2), encoding="utf-8")
        logger.info("LinkedIn token refreshed and saved")

        return self._token_data

    def get_headers(self) -> dict[str, str]:
        """Return authorization + API version headers for LinkedIn REST API."""
        token_data = self._ensure_token()
        return {
            "Authorization": f"Bearer {token_data['access_token']}",
            "LinkedIn-Version": "202401",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def get_person_urn(self) -> str:
        """Return the ``urn:li:person:{id}`` for the authenticated user."""
        token_data = self._ensure_token()
        person_id = token_data.get("person_id", "")
        if not person_id:
            msg = "person_id not found in linkedin_token.json. Re-run the auth script."
            raise LinkedInAuthError(msg)
        return f"urn:li:person:{person_id}"
