"""Tests for the SMS notification channel."""

from unittest.mock import AsyncMock, patch

from src.notifications.sms_channel import SMSChannel


def test_channel_name() -> None:
    """Channel name should be 'sms'."""
    channel = SMSChannel()
    assert channel.name == "sms"


async def test_send_delegates_to_send_sms() -> None:
    """send() should delegate to the Telnyx send_sms function."""
    channel = SMSChannel()

    with patch("src.notifications.sms_channel.send_sms", new_callable=AsyncMock) as mock:
        mock.return_value = True
        result = await channel.send("+15559876543", "Hello!")

    assert result is True
    mock.assert_awaited_once_with("+15559876543", "Hello!")


async def test_send_rich_strips_buttons() -> None:
    """send_rich() should ignore buttons and parse_mode, delegate to send()."""
    channel = SMSChannel()

    with patch("src.notifications.sms_channel.send_sms", new_callable=AsyncMock) as mock:
        mock.return_value = True
        result = await channel.send_rich(
            "+15559876543",
            "Message with buttons",
            buttons=[[{"text": "Click", "callback_data": "cb"}]],
            parse_mode="Markdown",
        )

    assert result is True
    mock.assert_awaited_once_with("+15559876543", "Message with buttons")


async def test_send_photo_returns_false() -> None:
    """send_photo() should return False (SMS can't send photos)."""
    channel = SMSChannel()
    result = await channel.send_photo("+15559876543", b"fake-photo-data", caption="A photo")
    assert result is False
