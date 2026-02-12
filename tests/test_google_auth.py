"""Tests for GoogleAuthManager multi-account registry."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.integrations.google_auth import GoogleAuthManager


@pytest.fixture(autouse=True)
def _reset_instances():
    """Clear the instance cache between tests."""
    GoogleAuthManager._instances = {}
    yield
    GoogleAuthManager._instances = {}


@pytest.fixture
def _accounts(monkeypatch):
    """Configure two accounts: work (default) and personal."""
    monkeypatch.setattr("src.integrations.google_auth.settings.google_accounts", "work,personal")
    monkeypatch.setattr("src.integrations.google_auth.settings.google_default_account", "work")


class TestGet:
    def test_default_account(self, _accounts):
        mgr = GoogleAuthManager.get()
        assert mgr._account == "work"
        assert mgr._token_path == Path("auth_tokens/google_work_auth_token.json")

    def test_explicit_account(self, _accounts):
        mgr = GoogleAuthManager.get("personal")
        assert mgr._account == "personal"
        assert mgr._token_path == Path("auth_tokens/google_personal_auth_token.json")

    def test_caching(self, _accounts):
        a = GoogleAuthManager.get("work")
        b = GoogleAuthManager.get("work")
        assert a is b

    def test_different_accounts_different_instances(self, _accounts):
        a = GoogleAuthManager.get("work")
        b = GoogleAuthManager.get("personal")
        assert a is not b

    def test_unknown_account_raises(self, _accounts):
        with pytest.raises(ValueError, match="not in GOOGLE_ACCOUNTS"):
            GoogleAuthManager.get("unknown")

    def test_no_accounts_configured_raises(self, monkeypatch):
        monkeypatch.setattr("src.integrations.google_auth.settings.google_accounts", "")
        with pytest.raises(ValueError, match="GOOGLE_ACCOUNTS is not configured"):
            GoogleAuthManager.get()

    def test_falls_back_to_first_account_when_no_default(self, monkeypatch):
        monkeypatch.setattr("src.integrations.google_auth.settings.google_accounts", "alpha,beta")
        monkeypatch.setattr("src.integrations.google_auth.settings.google_default_account", "")
        mgr = GoogleAuthManager.get()
        assert mgr._account == "alpha"


class TestAnyEnabled:
    def test_returns_true_when_token_exists(self, _accounts, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        (tmp_path / "auth_tokens/google_work_auth_token.json").write_text("{}")
        assert GoogleAuthManager.any_enabled() is True

    def test_returns_false_when_no_tokens(self, _accounts, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert GoogleAuthManager.any_enabled() is False

    def test_returns_false_when_no_accounts(self, monkeypatch):
        monkeypatch.setattr("src.integrations.google_auth.settings.google_accounts", "")
        assert GoogleAuthManager.any_enabled() is False


class TestEnabled:
    def test_enabled_when_token_exists(self, _accounts, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        (tmp_path / "auth_tokens/google_work_auth_token.json").write_text("{}")
        assert GoogleAuthManager.get("work").enabled is True

    def test_disabled_when_no_token(self, _accounts, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert GoogleAuthManager.get("work").enabled is False


class TestLoadCredentials:
    def test_missing_file_raises(self, _accounts, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError, match="scripts/google_auth.py --account work"):
            GoogleAuthManager.get("work")._load_credentials()

    @patch("src.integrations.google_auth.Credentials")
    def test_load_valid(self, mock_creds_cls, _accounts, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        (tmp_path / "auth_tokens/google_work_auth_token.json").write_text("{}")

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        creds = GoogleAuthManager.get("work")._load_credentials()
        assert creds is mock_creds

    @patch("src.integrations.google_auth.Request")
    @patch("src.integrations.google_auth.Credentials")
    def test_refreshes_expired(
        self, mock_creds_cls, mock_request_cls, _accounts, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        token = tmp_path / "auth_tokens/google_work_auth_token.json"
        token.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh-token"
        mock_creds.to_json.return_value = '{"refreshed": true}'
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        creds = GoogleAuthManager.get("work")._load_credentials()
        assert creds is mock_creds
        mock_creds.refresh.assert_called_once()
        assert token.read_text() == '{"refreshed": true}'


class TestServiceBuilders:
    @patch("src.integrations.google_auth.build")
    @patch("src.integrations.google_auth.Credentials")
    def test_gmail_service(self, mock_creds_cls, mock_build, _accounts, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        (tmp_path / "auth_tokens/google_work_auth_token.json").write_text("{}")
        mock_creds = MagicMock(expired=False)
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        GoogleAuthManager.get("work").gmail()
        mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)

    @patch("src.integrations.google_auth.build")
    @patch("src.integrations.google_auth.Credentials")
    def test_calendar_service(self, mock_creds_cls, mock_build, _accounts, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        (tmp_path / "auth_tokens/google_work_auth_token.json").write_text("{}")
        mock_creds = MagicMock(expired=False)
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        GoogleAuthManager.get("work").calendar()
        mock_build.assert_called_once_with("calendar", "v3", credentials=mock_creds)

    @patch("src.integrations.google_auth.build")
    @patch("src.integrations.google_auth.Credentials")
    def test_drive_service(self, mock_creds_cls, mock_build, _accounts, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        (tmp_path / "auth_tokens/google_work_auth_token.json").write_text("{}")
        mock_creds = MagicMock(expired=False)
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        GoogleAuthManager.get("work").drive()
        mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)

    @patch("src.integrations.google_auth.build")
    @patch("src.integrations.google_auth.Credentials")
    def test_docs_service(self, mock_creds_cls, mock_build, _accounts, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        (tmp_path / "auth_tokens/google_work_auth_token.json").write_text("{}")
        mock_creds = MagicMock(expired=False)
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        GoogleAuthManager.get("work").docs()
        mock_build.assert_called_once_with("docs", "v1", credentials=mock_creds)


class TestScopes:
    def test_scopes_include_all_services(self):
        scopes = GoogleAuthManager.SCOPES
        assert any("gmail" in s for s in scopes)
        assert any("calendar" in s for s in scopes)
        assert any("drive" in s for s in scopes)
        assert any("documents" in s for s in scopes)
