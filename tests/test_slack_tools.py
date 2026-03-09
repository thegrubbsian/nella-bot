"""Tests for Slack tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.slack_tools import (
    slack_find_user,
    slack_list_channels,
    slack_list_dms,
    slack_read_messages,
    slack_reply_to_thread,
    slack_search_messages,
    slack_send_message,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_user_client():
    """Return a mock AsyncWebClient for user-token calls."""
    return AsyncMock()


@pytest.fixture()
def mock_bot_client():
    """Return a mock AsyncWebClient for bot-token calls."""
    return AsyncMock()


@pytest.fixture()
def _mock_auth(mock_user_client, mock_bot_client):
    """Patch SlackAuthManager to return mocked clients."""
    mock_mgr = MagicMock()
    mock_mgr.user_client.return_value = mock_user_client
    mock_mgr.bot_client.return_value = mock_bot_client

    with patch("src.tools.slack_tools.SlackAuthManager") as cls:
        cls.get.return_value = mock_mgr
        yield


# ---------------------------------------------------------------------------
# slack_list_channels
# ---------------------------------------------------------------------------


async def test_list_channels_success(_mock_auth, mock_user_client) -> None:
    mock_user_client.conversations_list = AsyncMock(return_value={
        "channels": [
            {
                "id": "C123",
                "name": "general",
                "topic": {"value": "General chat"},
                "purpose": {"value": "Company-wide"},
                "num_members": 50,
                "is_private": False,
            },
        ],
    })
    result = await slack_list_channels()
    assert result.success
    assert result.data["count"] == 1
    assert result.data["channels"][0]["name"] == "general"


async def test_list_channels_error(_mock_auth, mock_user_client) -> None:
    mock_user_client.conversations_list = AsyncMock(side_effect=Exception("API error"))
    result = await slack_list_channels()
    assert not result.success
    assert "Failed to list channels" in result.error


# ---------------------------------------------------------------------------
# slack_list_dms
# ---------------------------------------------------------------------------


async def test_list_dms_success(_mock_auth, mock_user_client) -> None:
    mock_user_client.conversations_list = AsyncMock(return_value={
        "channels": [
            {"id": "D123", "user": "U456", "is_open": True},
        ],
    })
    mock_user_client.users_list = AsyncMock(return_value={
        "members": [
            {"id": "U456", "real_name": "Alice", "name": "alice"},
        ],
    })
    result = await slack_list_dms()
    assert result.success
    assert result.data["count"] == 1
    assert result.data["conversations"][0]["user_name"] == "Alice"


async def test_list_dms_error(_mock_auth, mock_user_client) -> None:
    mock_user_client.conversations_list = AsyncMock(side_effect=Exception("boom"))
    result = await slack_list_dms()
    assert not result.success


# ---------------------------------------------------------------------------
# slack_read_messages
# ---------------------------------------------------------------------------


async def test_read_messages_success(_mock_auth, mock_user_client) -> None:
    mock_user_client.conversations_history = AsyncMock(return_value={
        "messages": [
            {"user": "U123", "text": "Hello!", "ts": "1234.5678"},
        ],
        "has_more": False,
    })
    mock_user_client.users_info = AsyncMock(return_value={
        "user": {"id": "U123", "real_name": "Bob", "name": "bob"},
    })
    result = await slack_read_messages(channel="C123")
    assert result.success
    assert result.data["count"] == 1
    assert result.data["messages"][0]["user_name"] == "Bob"


async def test_read_messages_thread(_mock_auth, mock_user_client) -> None:
    mock_user_client.conversations_replies = AsyncMock(return_value={
        "messages": [
            {"user": "U123", "text": "Reply!", "ts": "1234.9999"},
        ],
    })
    mock_user_client.users_info = AsyncMock(return_value={
        "user": {"id": "U123", "real_name": "Bob"},
    })
    result = await slack_read_messages(channel="C123", thread_ts="1234.5678")
    assert result.success
    assert result.data["messages"][0]["text"] == "Reply!"


async def test_read_messages_error(_mock_auth, mock_user_client) -> None:
    mock_user_client.conversations_history = AsyncMock(side_effect=Exception("boom"))
    result = await slack_read_messages(channel="C123")
    assert not result.success


# ---------------------------------------------------------------------------
# slack_send_message
# ---------------------------------------------------------------------------


async def test_send_message_to_channel(_mock_auth, mock_user_client) -> None:
    mock_user_client.chat_postMessage = AsyncMock(return_value={"ts": "1234.5678"})
    result = await slack_send_message(target="C123", text="Hello channel!")
    assert result.success
    assert result.data["sent"] is True
    assert result.data["channel"] == "C123"


async def test_send_message_to_user(_mock_auth, mock_user_client) -> None:
    mock_user_client.conversations_open = AsyncMock(return_value={
        "channel": {"id": "D789"},
    })
    mock_user_client.chat_postMessage = AsyncMock(return_value={"ts": "1234.5678"})
    result = await slack_send_message(target="U456", text="Hello!")
    assert result.success
    assert result.data["channel"] == "D789"
    mock_user_client.conversations_open.assert_called_once_with(users=["U456"])


async def test_send_message_with_workspace(_mock_auth, mock_user_client) -> None:
    mock_user_client.chat_postMessage = AsyncMock(return_value={"ts": "1234.5678"})
    result = await slack_send_message(target="C123", text="Hi!", workspace="work")
    assert result.success


async def test_send_message_error(_mock_auth, mock_user_client) -> None:
    mock_user_client.chat_postMessage = AsyncMock(side_effect=Exception("boom"))
    result = await slack_send_message(target="C123", text="Hi!")
    assert not result.success


# ---------------------------------------------------------------------------
# slack_reply_to_thread
# ---------------------------------------------------------------------------


async def test_reply_to_thread_success(_mock_auth, mock_user_client) -> None:
    mock_user_client.chat_postMessage = AsyncMock(return_value={"ts": "1234.9999"})
    result = await slack_reply_to_thread(
        channel="C123", thread_ts="1234.5678", text="Reply!"
    )
    assert result.success
    assert result.data["thread_ts"] == "1234.5678"
    mock_user_client.chat_postMessage.assert_called_once_with(
        channel="C123", text="Reply!", thread_ts="1234.5678"
    )


async def test_reply_to_thread_error(_mock_auth, mock_user_client) -> None:
    mock_user_client.chat_postMessage = AsyncMock(side_effect=Exception("boom"))
    result = await slack_reply_to_thread(
        channel="C123", thread_ts="1234.5678", text="Reply!"
    )
    assert not result.success


# ---------------------------------------------------------------------------
# slack_search_messages
# ---------------------------------------------------------------------------


async def test_search_messages_success(_mock_auth, mock_user_client) -> None:
    mock_user_client.search_messages = AsyncMock(return_value={
        "messages": {
            "matches": [
                {
                    "text": "budget update",
                    "username": "alice",
                    "channel": {"name": "finance", "id": "C999"},
                    "ts": "1234.5678",
                    "permalink": "https://slack.com/archives/C999/p1234",
                },
            ],
            "total": 1,
        },
    })
    result = await slack_search_messages(query="budget")
    assert result.success
    assert result.data["count"] == 1
    assert result.data["matches"][0]["user"] == "alice"


async def test_search_messages_error(_mock_auth, mock_user_client) -> None:
    mock_user_client.search_messages = AsyncMock(side_effect=Exception("boom"))
    result = await slack_search_messages(query="test")
    assert not result.success


# ---------------------------------------------------------------------------
# slack_find_user
# ---------------------------------------------------------------------------


async def test_find_user_by_email(_mock_auth, mock_user_client) -> None:
    mock_user_client.users_lookupByEmail = AsyncMock(return_value={
        "user": {
            "id": "U123",
            "name": "alice",
            "real_name": "Alice Smith",
            "profile": {"display_name": "alice", "email": "alice@co.com", "title": "Eng"},
            "is_admin": False,
        },
    })
    result = await slack_find_user(query="alice@co.com")
    assert result.success
    assert result.data["count"] == 1
    assert result.data["match_type"] == "email"
    assert result.data["users"][0]["real_name"] == "Alice Smith"


async def test_find_user_by_name(_mock_auth, mock_user_client) -> None:
    mock_user_client.users_list = AsyncMock(return_value={
        "members": [
            {
                "id": "U123",
                "name": "alice",
                "real_name": "Alice Smith",
                "profile": {"display_name": "alice", "email": "alice@co.com", "title": ""},
                "is_admin": False,
                "deleted": False,
                "is_bot": False,
            },
            {
                "id": "U456",
                "name": "bob",
                "real_name": "Bob Jones",
                "profile": {"display_name": "bob", "email": "bob@co.com", "title": ""},
                "is_admin": False,
                "deleted": False,
                "is_bot": False,
            },
        ],
    })
    result = await slack_find_user(query="alice")
    assert result.success
    assert result.data["count"] == 1
    assert result.data["match_type"] == "name"
    assert result.data["users"][0]["id"] == "U123"


async def test_find_user_email_fallback_to_name(_mock_auth, mock_user_client) -> None:
    """If email lookup fails, falls back to name search."""
    mock_user_client.users_lookupByEmail = AsyncMock(side_effect=Exception("not found"))
    mock_user_client.users_list = AsyncMock(return_value={"members": []})
    result = await slack_find_user(query="nobody@co.com")
    assert result.success
    assert result.data["count"] == 0


async def test_find_user_error(_mock_auth, mock_user_client) -> None:
    mock_user_client.users_list = AsyncMock(side_effect=Exception("boom"))
    result = await slack_find_user(query="alice")
    assert not result.success
