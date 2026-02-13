"""Tests for SlackChannel and protocol conformance."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.notifications.channels import NotificationChannel
from src.notifications.slack_channel import SlackChannel


def _make_mock_client() -> AsyncMock:
    """Create a mock slack_sdk.web.async_client.AsyncWebClient."""
    client = AsyncMock()
    client.conversations_open = AsyncMock(
        return_value={"channel": {"id": "D01ABC123"}}
    )
    client.chat_postMessage = AsyncMock(return_value={"ok": True})
    return client


def test_slack_channel_satisfies_protocol() -> None:
    client = _make_mock_client()
    ch = SlackChannel(client)
    assert isinstance(ch, NotificationChannel)


def test_name_property() -> None:
    client = _make_mock_client()
    ch = SlackChannel(client)
    assert ch.name == "slack"


async def test_send_opens_dm_and_posts() -> None:
    client = _make_mock_client()
    ch = SlackChannel(client)

    ok = await ch.send("U01XYZ", "Hello there")
    assert ok is True
    client.conversations_open.assert_awaited_once_with(users=["U01XYZ"])
    client.chat_postMessage.assert_awaited_once_with(
        channel="D01ABC123", text="Hello there"
    )


async def test_send_returns_false_on_error() -> None:
    client = _make_mock_client()
    client.conversations_open.side_effect = RuntimeError("network down")
    ch = SlackChannel(client)

    ok = await ch.send("U01XYZ", "hi")
    assert ok is False


async def test_send_rich_without_buttons() -> None:
    client = _make_mock_client()
    ch = SlackChannel(client)

    ok = await ch.send_rich("U01XYZ", "Hello")
    assert ok is True
    client.chat_postMessage.assert_awaited_once()
    call_kwargs = client.chat_postMessage.call_args.kwargs
    assert call_kwargs["text"] == "Hello"
    assert "blocks" not in call_kwargs


async def test_send_rich_with_buttons() -> None:
    client = _make_mock_client()
    ch = SlackChannel(client)

    buttons = [
        [{"text": "Yes", "callback_data": "yes"}, {"text": "No", "callback_data": "no"}],
    ]

    ok = await ch.send_rich("U01XYZ", "Pick one", buttons=buttons)
    assert ok is True
    call_kwargs = client.chat_postMessage.call_args.kwargs
    assert "blocks" in call_kwargs


async def test_send_rich_returns_false_on_error() -> None:
    client = _make_mock_client()
    client.conversations_open.side_effect = RuntimeError("boom")
    ch = SlackChannel(client)

    ok = await ch.send_rich("U01XYZ", "hi")
    assert ok is False
