"""Tests for Slack message handlers."""

from unittest.mock import AsyncMock, patch

from src.bot.slack.handlers import handle_message


def _make_say() -> AsyncMock:
    """Create a mock say() that returns a Slack message response."""
    say = AsyncMock(return_value={"ts": "1234567890.123456", "channel": "D01ABC123"})
    return say


def _make_client() -> AsyncMock:
    client = AsyncMock()
    client.chat_update = AsyncMock()
    return client


async def test_handle_message_calls_generate_response() -> None:
    event = {"text": "Hello Nella", "user": "U01XYZ", "channel": "D01ABC123"}
    say = _make_say()
    client = _make_client()

    with (
        patch("src.bot.slack.handlers.generate_response", new_callable=AsyncMock) as mock_gen,
        patch("src.bot.slack.handlers.extract_and_save", new_callable=AsyncMock),
    ):
        mock_gen.return_value = "Hi there!"
        await handle_message(event=event, say=say, client=client)

    say.assert_awaited_once_with("...")
    mock_gen.assert_awaited_once()


async def test_handle_message_updates_placeholder() -> None:
    event = {"text": "Hello", "user": "U01XYZ", "channel": "D01ABC123"}
    say = _make_say()
    client = _make_client()

    with (
        patch("src.bot.slack.handlers.generate_response", new_callable=AsyncMock) as mock_gen,
        patch("src.bot.slack.handlers.extract_and_save", new_callable=AsyncMock),
    ):
        mock_gen.return_value = "Final response"
        await handle_message(event=event, say=say, client=client)

    # Final edit with the complete response
    client.chat_update.assert_awaited()


async def test_handle_message_creates_message_context() -> None:
    event = {"text": "Hello", "user": "U01XYZ", "channel": "D01ABC123"}
    say = _make_say()
    client = _make_client()

    with (
        patch("src.bot.slack.handlers.generate_response", new_callable=AsyncMock) as mock_gen,
        patch("src.bot.slack.handlers.extract_and_save", new_callable=AsyncMock),
    ):
        mock_gen.return_value = "Hi"
        await handle_message(event=event, say=say, client=client)

    call_kwargs = mock_gen.call_args
    msg_context = call_kwargs.kwargs["msg_context"]
    assert msg_context.source_channel == "slack"
    assert msg_context.user_id == "U01XYZ"
    assert msg_context.conversation_id == "D01ABC123"
