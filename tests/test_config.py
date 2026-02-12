"""Tests for Settings configuration model."""

import pytest

from src.config import Settings


class TestGetAllowedUserIds:
    def test_parses_comma_separated(self):
        s = Settings(allowed_user_ids="123,456,789")
        assert s.get_allowed_user_ids() == {123, 456, 789}

    def test_handles_spaces(self):
        s = Settings(allowed_user_ids=" 123 , 456 ")
        assert s.get_allowed_user_ids() == {123, 456}

    def test_empty_string_returns_empty_set(self):
        s = Settings(allowed_user_ids="")
        assert s.get_allowed_user_ids() == set()

    def test_single_id(self):
        s = Settings(allowed_user_ids="42")
        assert s.get_allowed_user_ids() == {42}


class TestGetGoogleAccounts:
    def test_parses_comma_separated(self):
        s = Settings(google_accounts="work,personal")
        assert s.get_google_accounts() == ["work", "personal"]

    def test_handles_spaces(self):
        s = Settings(google_accounts=" work , personal ")
        assert s.get_google_accounts() == ["work", "personal"]

    def test_empty_string_returns_empty_list(self):
        s = Settings(google_accounts="")
        assert s.get_google_accounts() == []

    def test_single_account(self):
        s = Settings(google_accounts="main")
        assert s.get_google_accounts() == ["main"]


class TestDefaults:
    def test_default_chat_model(self):
        s = Settings()
        assert s.default_chat_model == "sonnet"

    def test_default_memory_model(self):
        s = Settings()
        assert s.default_memory_model == "haiku"

    def test_default_database_path(self):
        from pathlib import Path

        s = Settings()
        assert s.database_path == Path("data/nella.db")

    def test_default_webhook_port(self):
        s = Settings()
        assert s.webhook_port == 8443

    def test_default_scheduler_timezone(self):
        s = Settings()
        assert s.scheduler_timezone == "America/Chicago"

    def test_memory_extraction_enabled_default(self):
        s = Settings()
        assert s.memory_extraction_enabled is True


class TestExtraForbidden:
    def test_unknown_env_var_raises(self):
        with pytest.raises(ValueError, match="extra_forbidden"):
            Settings(**{"nonexistent_field": "value"})
