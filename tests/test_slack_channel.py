"""Tests for the Slack notification channel."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.notifications.slack_channel import SlackChannel


@pytest.fixture()
def channel():
    return SlackChannel()


def test_name(channel) -> None:
    assert channel.name == "slack"


async def test_send_success(channel) -> None:
    with patch(
        "src.notifications.slack_channel.send_slack_message",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_send:
        result = await channel.send("C123", "Hello!")

    assert result is True
    mock_send.assert_called_once()


async def test_send_long_message_chunked(channel) -> None:
    """Long messages are split into chunks."""
    long_msg = "x" * 8000

    with patch(
        "src.notifications.slack_channel.send_slack_message",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_send:
        result = await channel.send("C123", long_msg)

    assert result is True
    assert mock_send.call_count >= 2


async def test_send_failure(channel) -> None:
    with patch(
        "src.notifications.slack_channel.send_slack_message",
        new_callable=AsyncMock,
        return_value=False,
    ):
        result = await channel.send("C123", "Hello!")

    assert result is False


async def test_send_rich_delegates_to_send(channel) -> None:
    with patch.object(channel, "send", new_callable=AsyncMock, return_value=True) as mock_send:
        result = await channel.send_rich("C123", "Hello!", buttons=[[{"text": "OK"}]])

    assert result is True
    mock_send.assert_called_once_with("C123", "Hello!")


async def test_send_photo_success(channel) -> None:
    mock_client = AsyncMock()
    mock_mgr = MagicMock()
    mock_mgr.bot_client.return_value = mock_client

    with patch("src.integrations.slack_auth.SlackAuthManager.get", return_value=mock_mgr):
        result = await channel.send_photo("C123", b"fake-png", caption="A photo")

    assert result is True
    mock_client.files_upload_v2.assert_called_once_with(
        channel="C123",
        content=b"fake-png",
        filename="image.png",
        initial_comment="A photo",
    )


async def test_send_photo_failure(channel) -> None:
    with patch(
        "src.integrations.slack_auth.SlackAuthManager.get",
        side_effect=ValueError("not configured"),
    ):
        result = await channel.send_photo("C123", b"fake-png")

    assert result is False
