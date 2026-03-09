"""Tests for the Slack message client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.slack.client import MAX_SLACK_LENGTH, send_slack_message


@pytest.fixture()
def mock_bot_client():
    """Return a mock AsyncWebClient."""
    client = AsyncMock()
    client.chat_postMessage = AsyncMock()
    return client


@pytest.fixture()
def mock_auth(mock_bot_client):
    """Patch SlackAuthManager.get() to return a manager with our mock client."""
    mock_mgr = MagicMock()
    mock_mgr.bot_client.return_value = mock_bot_client
    with patch("src.slack.client.SlackAuthManager") as cls:
        cls.get.return_value = mock_mgr
        yield cls, mock_bot_client


async def test_send_success(mock_auth) -> None:
    _, client = mock_auth
    result = await send_slack_message("C123", "Hello!")
    assert result is True
    client.chat_postMessage.assert_called_once_with(
        channel="C123", text="Hello!", thread_ts=None
    )


async def test_send_with_thread_ts(mock_auth) -> None:
    _, client = mock_auth
    result = await send_slack_message("C123", "Reply!", thread_ts="1234.5678")
    assert result is True
    client.chat_postMessage.assert_called_once_with(
        channel="C123", text="Reply!", thread_ts="1234.5678"
    )


async def test_send_with_workspace(mock_auth) -> None:
    cls, _ = mock_auth
    await send_slack_message("C123", "Hello!", workspace="work")
    cls.get.assert_called_once_with("work")


async def test_send_truncation(mock_auth) -> None:
    _, client = mock_auth
    long_text = "x" * 5000
    await send_slack_message("C123", long_text)

    call_kwargs = client.chat_postMessage.call_args
    sent_text = call_kwargs.kwargs.get("text") or call_kwargs[1].get("text")
    assert len(sent_text) == MAX_SLACK_LENGTH
    assert sent_text.endswith("...")


async def test_send_not_configured() -> None:
    with patch("src.slack.client.SlackAuthManager") as cls:
        cls.get.side_effect = ValueError("not configured")
        result = await send_slack_message("C123", "Hello!")
    assert result is False


async def test_send_api_error(mock_auth) -> None:
    _, client = mock_auth
    client.chat_postMessage.side_effect = Exception("API error")
    result = await send_slack_message("C123", "Hello!")
    assert result is False
