"""Tests for LinkedInAuth — single-account singleton."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from src.integrations.linkedin_auth import LinkedInAuth, LinkedInAuthError


@pytest.fixture(autouse=True)
def _reset():
    LinkedInAuth._reset()
    yield
    LinkedInAuth._reset()


class TestSingleton:
    def test_get_returns_same_instance(self):
        a = LinkedInAuth.get()
        b = LinkedInAuth.get()
        assert a is b

    def test_reset_clears_instance(self):
        a = LinkedInAuth.get()
        LinkedInAuth._reset()
        b = LinkedInAuth.get()
        assert a is not b


class TestEnabled:
    def test_enabled_when_token_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        (tmp_path / "auth_tokens/linkedin_default_auth_token.json").write_text("{}")
        assert LinkedInAuth.enabled() is True

    def test_disabled_when_no_token(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert LinkedInAuth.enabled() is False


class TestLoadToken:
    def test_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        auth = LinkedInAuth.get()
        with pytest.raises(LinkedInAuthError, match="token file not found"):
            auth._load_token()

    def test_loads_valid_token(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        token_data = {"access_token": "abc123", "expires_at": time.time() + 3600}
        (tmp_path / "auth_tokens/linkedin_default_auth_token.json").write_text(
            json.dumps(token_data)
        )
        auth = LinkedInAuth.get()
        result = auth._load_token()
        assert result["access_token"] == "abc123"


class TestEnsureToken:
    def test_returns_valid_token(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        token_data = {"access_token": "valid", "expires_at": time.time() + 3600}
        (tmp_path / "auth_tokens/linkedin_default_auth_token.json").write_text(
            json.dumps(token_data)
        )
        auth = LinkedInAuth.get()
        result = auth._ensure_token()
        assert result["access_token"] == "valid"

    def test_expired_no_refresh_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        token_data = {"access_token": "expired", "expires_at": time.time() - 100}
        (tmp_path / "auth_tokens/linkedin_default_auth_token.json").write_text(
            json.dumps(token_data)
        )
        auth = LinkedInAuth.get()
        with pytest.raises(LinkedInAuthError, match="expired"):
            auth._ensure_token()

    @patch("src.integrations.linkedin_auth.httpx.post")
    def test_refresh_success(self, mock_post, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("src.config.settings.linkedin_client_id", "cid")
        monkeypatch.setattr("src.config.settings.linkedin_client_secret", "csecret")
        (tmp_path / "auth_tokens").mkdir()
        token_data = {
            "access_token": "old",
            "expires_at": time.time() - 100,
            "refresh_token": "refresh123",
        }
        (tmp_path / "auth_tokens/linkedin_default_auth_token.json").write_text(
            json.dumps(token_data)
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new_token",
            "expires_in": 5184000,
        }
        mock_post.return_value = mock_resp

        auth = LinkedInAuth.get()
        result = auth._ensure_token()
        assert result["access_token"] == "new_token"

    @patch("src.integrations.linkedin_auth.httpx.post")
    def test_refresh_failure_raises(self, mock_post, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("src.config.settings.linkedin_client_id", "cid")
        monkeypatch.setattr("src.config.settings.linkedin_client_secret", "csecret")
        (tmp_path / "auth_tokens").mkdir()
        token_data = {
            "access_token": "old",
            "expires_at": time.time() - 100,
            "refresh_token": "refresh123",
        }
        (tmp_path / "auth_tokens/linkedin_default_auth_token.json").write_text(
            json.dumps(token_data)
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_post.return_value = mock_resp

        auth = LinkedInAuth.get()
        with pytest.raises(LinkedInAuthError, match="refresh failed"):
            auth._ensure_token()


class TestGetHeaders:
    def test_returns_auth_headers(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        token_data = {"access_token": "mytoken", "expires_at": time.time() + 3600}
        (tmp_path / "auth_tokens/linkedin_default_auth_token.json").write_text(
            json.dumps(token_data)
        )
        auth = LinkedInAuth.get()
        headers = auth.get_headers()
        assert headers["Authorization"] == "Bearer mytoken"
        assert "LinkedIn-Version" in headers


class TestGetPersonUrn:
    def test_returns_urn(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        token_data = {
            "access_token": "tok",
            "expires_at": time.time() + 3600,
            "person_id": "abc123",
        }
        (tmp_path / "auth_tokens/linkedin_default_auth_token.json").write_text(
            json.dumps(token_data)
        )
        auth = LinkedInAuth.get()
        assert auth.get_person_urn() == "urn:li:person:abc123"

    def test_missing_person_id_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth_tokens").mkdir()
        token_data = {"access_token": "tok", "expires_at": time.time() + 3600}
        (tmp_path / "auth_tokens/linkedin_default_auth_token.json").write_text(
            json.dumps(token_data)
        )
        auth = LinkedInAuth.get()
        with pytest.raises(LinkedInAuthError, match="person_id"):
            auth.get_person_urn()
