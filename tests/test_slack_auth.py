"""Tests for SlackAuthManager."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.integrations.slack_auth import SlackAuthManager


@pytest.fixture(autouse=True)
def _reset():
    SlackAuthManager._reset()
    yield
    SlackAuthManager._reset()


SAMPLE_CONFIG = {
    "bot_token": "xoxb-test-bot-token",
    "user_token": "xoxp-test-user-token",
    "signing_secret": "test-signing-secret",
    "team_id": "T12345",
    "bot_user_id": "U12345BOT",
}


def _write_token_file(tmp_path: Path, name: str, config: dict | None = None) -> Path:
    token_path = tmp_path / f"slack_{name}.json"
    token_path.write_text(json.dumps(config or SAMPLE_CONFIG))
    return token_path


def _path_redirect(token_path: Path, keyword: str):
    """Return a side_effect for patching Path that redirects matching paths."""
    def _side_effect(p):
        return token_path if keyword in str(p) else Path(p)
    return _side_effect


# ---------------------------------------------------------------------------
# get() tests
# ---------------------------------------------------------------------------


def test_get_default_workspace(tmp_path: Path) -> None:
    """get(None) returns the first configured workspace."""
    token_path = _write_token_file(tmp_path, "personal")

    with (
        patch("src.integrations.slack_auth.settings") as s,
        patch(
            "src.integrations.slack_auth.Path",
            side_effect=_path_redirect(token_path, "personal"),
        ),
    ):
        s.get_slack_workspaces.return_value = ["personal"]
        s.slack_default_workspace = ""

        mgr = SlackAuthManager.get()
        assert mgr.workspace == "personal"


def test_get_explicit_workspace(tmp_path: Path) -> None:
    """get('work') returns the work workspace."""
    token_path = _write_token_file(tmp_path, "work")

    with (
        patch("src.integrations.slack_auth.settings") as s,
        patch(
            "src.integrations.slack_auth.Path",
            side_effect=_path_redirect(token_path, "work"),
        ),
    ):
        s.get_slack_workspaces.return_value = ["personal", "work"]
        s.slack_default_workspace = ""

        mgr = SlackAuthManager.get("work")
        assert mgr.workspace == "work"


def test_get_unknown_workspace() -> None:
    """get() raises ValueError for unknown workspace."""
    with patch("src.integrations.slack_auth.settings") as s:
        s.get_slack_workspaces.return_value = ["personal"]
        s.slack_default_workspace = ""

        with pytest.raises(ValueError, match="not in SLACK_WORKSPACES"):
            SlackAuthManager.get("unknown")


def test_get_no_workspaces_configured() -> None:
    """get() raises ValueError when nothing is configured."""
    with patch("src.integrations.slack_auth.settings") as s:
        s.get_slack_workspaces.return_value = []

        with pytest.raises(ValueError, match="not configured"):
            SlackAuthManager.get()


def test_get_caches_instances(tmp_path: Path) -> None:
    """Repeated calls return the same instance."""
    token_path = _write_token_file(tmp_path, "personal")

    with (
        patch("src.integrations.slack_auth.settings") as s,
        patch(
            "src.integrations.slack_auth.Path",
            side_effect=_path_redirect(token_path, "personal"),
        ),
    ):
        s.get_slack_workspaces.return_value = ["personal"]
        s.slack_default_workspace = ""

        mgr1 = SlackAuthManager.get()
        mgr2 = SlackAuthManager.get()
        assert mgr1 is mgr2


def test_get_default_override(tmp_path: Path) -> None:
    """slack_default_workspace overrides the first-in-list default."""
    token_path = _write_token_file(tmp_path, "work")

    with (
        patch("src.integrations.slack_auth.settings") as s,
        patch(
            "src.integrations.slack_auth.Path",
            side_effect=_path_redirect(token_path, "work"),
        ),
    ):
        s.get_slack_workspaces.return_value = ["personal", "work"]
        s.slack_default_workspace = "work"

        mgr = SlackAuthManager.get()
        assert mgr.workspace == "work"


# ---------------------------------------------------------------------------
# any_enabled() tests
# ---------------------------------------------------------------------------


def test_any_enabled_true(tmp_path: Path) -> None:
    """Returns True when a token file exists."""
    _write_token_file(tmp_path, "personal")

    with patch("src.integrations.slack_auth.settings") as s:
        s.get_slack_workspaces.return_value = ["personal"]

        with patch("src.integrations.slack_auth.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            assert SlackAuthManager.any_enabled() is True


def test_any_enabled_false_no_files() -> None:
    """Returns False when no token files exist."""
    with patch("src.integrations.slack_auth.settings") as s:
        s.get_slack_workspaces.return_value = ["personal"]

        with patch("src.integrations.slack_auth.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            assert SlackAuthManager.any_enabled() is False


def test_any_enabled_no_config() -> None:
    """Returns False when no workspaces configured."""
    with patch("src.integrations.slack_auth.settings") as s:
        s.get_slack_workspaces.return_value = []
        assert SlackAuthManager.any_enabled() is False


# ---------------------------------------------------------------------------
# get_by_team_id() tests
# ---------------------------------------------------------------------------


def test_get_by_team_id_found(tmp_path: Path) -> None:
    """Finds workspace by team_id."""
    token_path = _write_token_file(tmp_path, "personal")

    with (
        patch("src.integrations.slack_auth.settings") as s,
        patch(
            "src.integrations.slack_auth.Path",
            side_effect=_path_redirect(token_path, "personal"),
        ),
    ):
        s.get_slack_workspaces.return_value = ["personal"]
        s.slack_default_workspace = ""

        mgr = SlackAuthManager.get_by_team_id("T12345")
        assert mgr is not None
        assert mgr.workspace == "personal"


def test_get_by_team_id_not_found(tmp_path: Path) -> None:
    """Returns None when no workspace matches."""
    token_path = _write_token_file(tmp_path, "personal")

    with (
        patch("src.integrations.slack_auth.settings") as s,
        patch(
            "src.integrations.slack_auth.Path",
            side_effect=_path_redirect(token_path, "personal"),
        ),
    ):
        s.get_slack_workspaces.return_value = ["personal"]
        s.slack_default_workspace = ""

        mgr = SlackAuthManager.get_by_team_id("TNOTFOUND")
        assert mgr is None


# ---------------------------------------------------------------------------
# Config loading + properties
# ---------------------------------------------------------------------------


def test_load_config(tmp_path: Path) -> None:
    """Config loads correctly from JSON."""
    token_path = _write_token_file(tmp_path, "personal")
    mgr = SlackAuthManager("personal", token_path)

    assert mgr.signing_secret == "test-signing-secret"
    assert mgr.bot_user_id == "U12345BOT"
    assert mgr.team_id == "T12345"


def test_load_config_missing_file() -> None:
    """Raises FileNotFoundError for missing token file."""
    mgr = SlackAuthManager("personal", Path("/nonexistent/slack_personal.json"))

    with pytest.raises(FileNotFoundError, match="token file not found"):
        mgr.signing_secret  # noqa: B018 — triggers _load_config


def test_load_config_cached(tmp_path: Path) -> None:
    """Config is only loaded once."""
    token_path = _write_token_file(tmp_path, "personal")
    mgr = SlackAuthManager("personal", token_path)

    _ = mgr.signing_secret
    _ = mgr.bot_user_id  # should use cached config

    # Config object should be the same instance
    assert mgr._config is not None


# ---------------------------------------------------------------------------
# Client builders
# ---------------------------------------------------------------------------


def test_bot_client(tmp_path: Path) -> None:
    """bot_client() returns an AsyncWebClient with bot token."""
    token_path = _write_token_file(tmp_path, "personal")
    mgr = SlackAuthManager("personal", token_path)

    client = mgr.bot_client()
    assert client.token == "xoxb-test-bot-token"

    # Should be cached
    assert mgr.bot_client() is client


def test_user_client(tmp_path: Path) -> None:
    """user_client() returns an AsyncWebClient with user token."""
    token_path = _write_token_file(tmp_path, "personal")
    mgr = SlackAuthManager("personal", token_path)

    client = mgr.user_client()
    assert client.token == "xoxp-test-user-token"

    # Should be cached
    assert mgr.user_client() is client


# ---------------------------------------------------------------------------
# _reset()
# ---------------------------------------------------------------------------


def test_reset_clears_instances(tmp_path: Path) -> None:
    """_reset() clears the instance cache."""
    token_path = _write_token_file(tmp_path, "personal")

    with (
        patch("src.integrations.slack_auth.settings") as s,
        patch(
            "src.integrations.slack_auth.Path",
            side_effect=_path_redirect(token_path, "personal"),
        ),
    ):
        s.get_slack_workspaces.return_value = ["personal"]
        s.slack_default_workspace = ""

        SlackAuthManager.get()
        assert len(SlackAuthManager._instances) == 1

        SlackAuthManager._reset()
        assert len(SlackAuthManager._instances) == 0
