"""Tests for GoogleAuthManager."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.integrations.google_auth import GoogleAuthManager


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the singleton between tests."""
    GoogleAuthManager._instance = None
    yield
    GoogleAuthManager._instance = None


class TestGoogleAuthManager:
    def test_singleton(self):
        a = GoogleAuthManager.get()
        b = GoogleAuthManager.get()
        assert a is b

    def test_enabled_when_token_exists(self, tmp_path, monkeypatch):
        token = tmp_path / "token.json"
        token.write_text("{}")
        monkeypatch.setattr("src.integrations.google_auth.settings.google_token_path", str(token))
        assert GoogleAuthManager.get().enabled is True

    def test_disabled_when_no_token(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.integrations.google_auth.settings.google_token_path",
            str(tmp_path / "nonexistent.json"),
        )
        assert GoogleAuthManager.get().enabled is False

    def test_load_credentials_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.integrations.google_auth.settings.google_token_path",
            str(tmp_path / "nonexistent.json"),
        )
        with pytest.raises(FileNotFoundError, match="Run.*scripts/google_auth.py"):
            GoogleAuthManager.get()._load_credentials()

    @patch("src.integrations.google_auth.Credentials")
    def test_load_credentials_valid(self, mock_creds_cls, tmp_path, monkeypatch):
        token = tmp_path / "token.json"
        token.write_text("{}")
        monkeypatch.setattr("src.integrations.google_auth.settings.google_token_path", str(token))

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        creds = GoogleAuthManager.get()._load_credentials()
        assert creds is mock_creds
        mock_creds_cls.from_authorized_user_file.assert_called_once()

    @patch("src.integrations.google_auth.Request")
    @patch("src.integrations.google_auth.Credentials")
    def test_load_credentials_refreshes_expired(
        self, mock_creds_cls, mock_request_cls, tmp_path, monkeypatch
    ):
        token = tmp_path / "token.json"
        token.write_text("{}")
        monkeypatch.setattr("src.integrations.google_auth.settings.google_token_path", str(token))

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh-token"
        mock_creds.to_json.return_value = '{"refreshed": true}'
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        creds = GoogleAuthManager.get()._load_credentials()
        assert creds is mock_creds
        mock_creds.refresh.assert_called_once()
        # Token file should be updated
        assert Path(token).read_text() == '{"refreshed": true}'

    @patch("src.integrations.google_auth.build")
    @patch("src.integrations.google_auth.Credentials")
    def test_gmail_service(self, mock_creds_cls, mock_build, tmp_path, monkeypatch):
        token = tmp_path / "token.json"
        token.write_text("{}")
        monkeypatch.setattr("src.integrations.google_auth.settings.google_token_path", str(token))

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        GoogleAuthManager.get().gmail()
        mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)

    @patch("src.integrations.google_auth.build")
    @patch("src.integrations.google_auth.Credentials")
    def test_calendar_service(self, mock_creds_cls, mock_build, tmp_path, monkeypatch):
        token = tmp_path / "token.json"
        token.write_text("{}")
        monkeypatch.setattr("src.integrations.google_auth.settings.google_token_path", str(token))

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        GoogleAuthManager.get().calendar()
        mock_build.assert_called_once_with("calendar", "v3", credentials=mock_creds)

    @patch("src.integrations.google_auth.build")
    @patch("src.integrations.google_auth.Credentials")
    def test_drive_service(self, mock_creds_cls, mock_build, tmp_path, monkeypatch):
        token = tmp_path / "token.json"
        token.write_text("{}")
        monkeypatch.setattr("src.integrations.google_auth.settings.google_token_path", str(token))

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        GoogleAuthManager.get().drive()
        mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)

    @patch("src.integrations.google_auth.build")
    @patch("src.integrations.google_auth.Credentials")
    def test_docs_service(self, mock_creds_cls, mock_build, tmp_path, monkeypatch):
        token = tmp_path / "token.json"
        token.write_text("{}")
        monkeypatch.setattr("src.integrations.google_auth.settings.google_token_path", str(token))

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        GoogleAuthManager.get().docs()
        mock_build.assert_called_once_with("docs", "v1", credentials=mock_creds)

    def test_scopes_include_all_services(self):
        scopes = GoogleAuthManager.SCOPES
        assert any("gmail" in s for s in scopes)
        assert any("calendar" in s for s in scopes)
        assert any("drive" in s for s in scopes)
        assert any("documents" in s for s in scopes)
