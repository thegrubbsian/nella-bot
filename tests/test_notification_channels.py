"""Tests for TelegramChannel and protocol conformance."""

from unittest.mock import AsyncMock, patch

from src.notifications.channels import NotificationChannel
from src.notifications.telegram_channel import TelegramChannel

# -- Helpers -----------------------------------------------------------------


def _make_mock_bot() -> AsyncMock:
    """Create a mock telegram.Bot."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


# -- Protocol conformance ---------------------------------------------------


def test_telegram_channel_satisfies_protocol() -> None:
    bot = _make_mock_bot()
    ch = TelegramChannel(bot)
    assert isinstance(ch, NotificationChannel)


def test_name_property() -> None:
    bot = _make_mock_bot()
    ch = TelegramChannel(bot)
    assert ch.name == "telegram"


# -- send() -----------------------------------------------------------------


async def test_send_calls_bot_send_message() -> None:
    bot = _make_mock_bot()
    ch = TelegramChannel(bot)

    ok = await ch.send("12345", "Hello there")
    assert ok is True
    bot.send_message.assert_awaited_once_with(
        chat_id=12345, text="Hello there", parse_mode="Markdown"
    )


async def test_send_converts_user_id_to_int() -> None:
    bot = _make_mock_bot()
    ch = TelegramChannel(bot)

    await ch.send("99999", "test")
    call_kwargs = bot.send_message.call_args
    assert call_kwargs.kwargs["chat_id"] == 99999


async def test_send_returns_false_on_error() -> None:
    bot = _make_mock_bot()
    bot.send_message.side_effect = RuntimeError("network down")
    ch = TelegramChannel(bot)

    ok = await ch.send("1", "hi")
    assert ok is False


# -- send_rich() -------------------------------------------------------------


async def test_send_rich_without_buttons() -> None:
    bot = _make_mock_bot()
    ch = TelegramChannel(bot)

    ok = await ch.send_rich("1", "Hello")
    assert ok is True
    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.call_args.kwargs
    assert call_kwargs["reply_markup"] is None
    assert call_kwargs["parse_mode"] == "Markdown"


async def test_send_rich_with_buttons() -> None:
    bot = _make_mock_bot()
    ch = TelegramChannel(bot)

    buttons = [
        [{"text": "Yes", "callback_data": "yes"}, {"text": "No", "callback_data": "no"}],
        [{"text": "Help", "url": "https://example.com"}],
    ]

    with (
        patch("src.notifications.telegram_channel.InlineKeyboardMarkup") as mock_markup,
        patch("src.notifications.telegram_channel.InlineKeyboardButton") as mock_button,
    ):
        mock_button.side_effect = lambda **kw: kw
        mock_markup.return_value = "MARKUP"

        ok = await ch.send_rich("1", "Pick one", buttons=buttons, parse_mode="HTML")
        assert ok is True
        assert mock_button.call_count == 3
        mock_markup.assert_called_once()
        bot.send_message.assert_awaited_once()
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["reply_markup"] == "MARKUP"
        assert call_kwargs["parse_mode"] == "HTML"


async def test_send_rich_custom_parse_mode() -> None:
    bot = _make_mock_bot()
    ch = TelegramChannel(bot)

    await ch.send_rich("1", "text", parse_mode="HTML")
    call_kwargs = bot.send_message.call_args.kwargs
    assert call_kwargs["parse_mode"] == "HTML"


async def test_send_rich_returns_false_on_error() -> None:
    bot = _make_mock_bot()
    bot.send_message.side_effect = RuntimeError("boom")
    ch = TelegramChannel(bot)

    ok = await ch.send_rich("1", "hi")
    assert ok is False
