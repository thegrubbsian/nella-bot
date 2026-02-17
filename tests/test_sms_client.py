"""Tests for the Telnyx SMS client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sms.client import MAX_SMS_LENGTH, send_sms


@pytest.fixture(autouse=True)
def _reset_session():
    """Reset the module-level aiohttp session between tests."""
    import src.sms.client as mod

    mod._session = None
    yield
    mod._session = None


@pytest.fixture()
def _sms_settings():
    """Provide valid SMS settings."""
    with (
        patch("src.sms.client.settings") as mock_settings,
    ):
        mock_settings.telnyx_api_key = "test-api-key"
        mock_settings.telnyx_phone_number = "+15551234567"
        yield mock_settings


async def test_send_sms_success(_sms_settings) -> None:
    """Successful send returns True."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.closed = False

    with patch("src.sms.client._get_session", return_value=mock_session):
        result = await send_sms("+15559876543", "Hello!")

    assert result is True
    mock_session.post.assert_called_once()
    call_kwargs = mock_session.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert payload["to"] == "+15559876543"
    assert payload["text"] == "Hello!"
    assert payload["from"] == "+15551234567"
    assert payload["type"] == "SMS"


async def test_send_sms_failure(_sms_settings) -> None:
    """Failed send returns False."""
    mock_resp = AsyncMock()
    mock_resp.status = 422
    mock_resp.text = AsyncMock(return_value="Bad request")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.closed = False

    with patch("src.sms.client._get_session", return_value=mock_session):
        result = await send_sms("+15559876543", "Hello!")

    assert result is False


async def test_send_sms_truncation(_sms_settings) -> None:
    """Messages exceeding MAX_SMS_LENGTH are truncated."""
    long_body = "x" * 2000

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.closed = False

    with patch("src.sms.client._get_session", return_value=mock_session):
        await send_sms("+15559876543", long_body)

    call_kwargs = mock_session.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert len(payload["text"]) == MAX_SMS_LENGTH
    assert payload["text"].endswith("...")


async def test_send_sms_not_configured() -> None:
    """Returns False when settings are missing."""
    with patch("src.sms.client.settings") as mock_settings:
        mock_settings.telnyx_api_key = ""
        mock_settings.telnyx_phone_number = ""
        result = await send_sms("+15559876543", "Hello!")

    assert result is False


async def test_send_sms_network_error(_sms_settings) -> None:
    """Network errors return False."""
    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=Exception("Connection refused"))
    mock_session.closed = False

    with patch("src.sms.client._get_session", return_value=mock_session):
        result = await send_sms("+15559876543", "Hello!")

    assert result is False


async def test_send_sms_auth_header(_sms_settings) -> None:
    """The lazy session is created with the correct auth header."""
    import src.sms.client as mod

    mod._session = None

    with patch("src.sms.client.aiohttp.ClientSession") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.closed = False
        mock_cls.return_value = mock_instance

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_instance.post = MagicMock(return_value=mock_resp)

        await send_sms("+15559876543", "Hello!")

        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["Authorization"] == "Bearer test-api-key"
