"""Tests for Slack tools (slack_list_users, slack_get_user_profile)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.tools.slack_tools import (
    SlackGetUserProfileParams,
    SlackListUsersParams,
    init_slack_tools,
    slack_get_user_profile,
    slack_list_users,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MEMBERS = [
    {
        "id": "U001",
        "name": "alice",
        "real_name": "Alice Smith",
        "is_bot": False,
        "is_admin": True,
        "profile": {"display_name": "alice.s"},
    },
    {
        "id": "U002",
        "name": "bob",
        "real_name": "Bob Jones",
        "is_bot": False,
        "is_admin": False,
        "profile": {"display_name": "bob.j"},
    },
    {
        "id": "U003",
        "name": "testbot",
        "real_name": "Test Bot",
        "is_bot": True,
        "is_admin": False,
        "profile": {"display_name": "testbot"},
    },
    {
        "id": "USLACKBOT",
        "name": "slackbot",
        "real_name": "Slackbot",
        "is_bot": False,
        "is_admin": False,
        "profile": {"display_name": "Slackbot"},
    },
]


def _make_mock_client(members: list[dict], paginate: bool = False) -> AsyncMock:
    """Create a mock AsyncWebClient that returns the given members."""
    client = AsyncMock()

    if paginate:
        # Split members into two pages — use MagicMock so .get() is sync
        mid = len(members) // 2
        page1_data = {
            "members": members[:mid],
            "response_metadata": {"next_cursor": "cursor_page2"},
        }
        page1 = MagicMock()
        page1.get.side_effect = page1_data.get

        page2_data = {
            "members": members[mid:],
            "response_metadata": {"next_cursor": ""},
        }
        page2 = MagicMock()
        page2.get.side_effect = page2_data.get

        client.users_list = AsyncMock(side_effect=[page1, page2])
    else:
        resp_data = {
            "members": members,
            "response_metadata": {"next_cursor": ""},
        }
        response = MagicMock()
        response.get.side_effect = resp_data.get
        client.users_list = AsyncMock(return_value=response)

    return client


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the module-level client before each test."""
    import src.tools.slack_tools as mod

    original = mod._slack_client
    mod._slack_client = None
    yield
    mod._slack_client = original


# ---------------------------------------------------------------------------
# Client initialization tests
# ---------------------------------------------------------------------------


class TestClientInit:
    async def test_error_when_not_initialized(self) -> None:
        result = await slack_list_users()
        assert not result.success
        assert "not initialized" in result.error

    async def test_init_sets_client(self) -> None:
        mock_client = _make_mock_client([])
        init_slack_tools(mock_client)
        result = await slack_list_users()
        assert result.success


# ---------------------------------------------------------------------------
# slack_list_users tests
# ---------------------------------------------------------------------------


class TestSlackListUsers:
    async def test_returns_users(self) -> None:
        mock_client = _make_mock_client(SAMPLE_MEMBERS)
        init_slack_tools(mock_client)

        result = await slack_list_users()

        assert result.success
        # Bots filtered out by default (testbot + slackbot)
        assert result.data["count"] == 2
        names = [u["name"] for u in result.data["users"]]
        assert "alice" in names
        assert "bob" in names
        assert "testbot" not in names
        assert "slackbot" not in names

    async def test_include_bots(self) -> None:
        mock_client = _make_mock_client(SAMPLE_MEMBERS)
        init_slack_tools(mock_client)

        result = await slack_list_users(include_bots=True)

        assert result.success
        assert result.data["count"] == 4
        names = [u["name"] for u in result.data["users"]]
        assert "testbot" in names
        assert "slackbot" in names

    async def test_slackbot_treated_as_bot(self) -> None:
        """USLACKBOT has is_bot=False but should be treated as a bot."""
        mock_client = _make_mock_client(SAMPLE_MEMBERS)
        init_slack_tools(mock_client)

        result = await slack_list_users(include_bots=False)

        ids = [u["id"] for u in result.data["users"]]
        assert "USLACKBOT" not in ids

    async def test_user_fields(self) -> None:
        mock_client = _make_mock_client(SAMPLE_MEMBERS[:1])
        init_slack_tools(mock_client)

        result = await slack_list_users()

        user = result.data["users"][0]
        assert user["id"] == "U001"
        assert user["name"] == "alice"
        assert user["real_name"] == "Alice Smith"
        assert user["display_name"] == "alice.s"
        assert user["is_bot"] is False
        assert user["is_admin"] is True

    async def test_pagination(self) -> None:
        mock_client = _make_mock_client(SAMPLE_MEMBERS, paginate=True)
        init_slack_tools(mock_client)

        result = await slack_list_users(include_bots=True)

        assert result.success
        assert result.data["count"] == 4
        assert mock_client.users_list.call_count == 2

    async def test_api_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.users_list = AsyncMock(side_effect=Exception("rate_limited"))
        init_slack_tools(mock_client)

        result = await slack_list_users()

        assert not result.success
        assert "rate_limited" in result.error


# ---------------------------------------------------------------------------
# Params validation tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# slack_get_user_profile tests
# ---------------------------------------------------------------------------

SAMPLE_PROFILE = {
    "real_name": "Alice Smith",
    "display_name": "alice.s",
    "email": "alice@example.com",
    "title": "Staff Engineer",
    "phone": "+1-555-0100",
    "status_text": "In a meeting",
    "status_emoji": ":calendar:",
    "tz": "America/New_York",
    "image_192": "https://avatars.slack.com/alice_192.png",
}


def _make_profile_client(profile: dict) -> AsyncMock:
    """Create a mock client whose users_profile_get returns *profile*."""
    client = AsyncMock()
    resp = MagicMock()
    resp.get.side_effect = {"profile": profile}.get
    client.users_profile_get = AsyncMock(return_value=resp)
    return client


class TestSlackGetUserProfile:
    async def test_success(self) -> None:
        mock_client = _make_profile_client(SAMPLE_PROFILE)
        init_slack_tools(mock_client)

        result = await slack_get_user_profile(user_id="U001")

        assert result.success
        assert result.data["user_id"] == "U001"
        assert result.data["real_name"] == "Alice Smith"
        assert result.data["display_name"] == "alice.s"
        assert result.data["email"] == "alice@example.com"
        assert result.data["title"] == "Staff Engineer"
        assert result.data["phone"] == "+1-555-0100"
        assert result.data["status_text"] == "In a meeting"
        assert result.data["status_emoji"] == ":calendar:"
        assert result.data["timezone"] == "America/New_York"
        assert result.data["image_url"] == "https://avatars.slack.com/alice_192.png"

    async def test_passes_user_id_to_api(self) -> None:
        mock_client = _make_profile_client({})
        init_slack_tools(mock_client)

        await slack_get_user_profile(user_id="U999")

        mock_client.users_profile_get.assert_awaited_once_with(user="U999")

    async def test_missing_fields_default_to_empty(self) -> None:
        mock_client = _make_profile_client({})
        init_slack_tools(mock_client)

        result = await slack_get_user_profile(user_id="U001")

        assert result.success
        assert result.data["email"] == ""
        assert result.data["title"] == ""
        assert result.data["phone"] == ""

    async def test_client_not_initialized(self) -> None:
        result = await slack_get_user_profile(user_id="U001")

        assert not result.success
        assert "not initialized" in result.error

    async def test_api_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.users_profile_get = AsyncMock(
            side_effect=Exception("user_not_found")
        )
        init_slack_tools(mock_client)

        result = await slack_get_user_profile(user_id="UBAD")

        assert not result.success
        assert "user_not_found" in result.error


# ---------------------------------------------------------------------------
# Params validation tests
# ---------------------------------------------------------------------------


class TestParams:
    def test_list_users_defaults(self) -> None:
        p = SlackListUsersParams()
        assert p.include_bots is False

    def test_list_users_include_bots_true(self) -> None:
        p = SlackListUsersParams(include_bots=True)
        assert p.include_bots is True

    def test_get_profile_requires_user_id(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SlackGetUserProfileParams()  # type: ignore[call-arg]

    def test_get_profile_valid(self) -> None:
        p = SlackGetUserProfileParams(user_id="U001")
        assert p.user_id == "U001"
