"""Tests for the SMS inbound webhook route."""

from unittest.mock import AsyncMock, patch

import pytest


def _telnyx_inbound_payload(
    from_number: str = "+15559876543",
    text: str = "Hey Nella",
    event_type: str = "message.received",
) -> dict:
    """Build a Telnyx-style inbound SMS payload."""
    return {
        "data": {
            "event_type": event_type,
            "payload": {
                "from": {"phone_number": from_number},
                "to": [{"phone_number": "+15551234567"}],
                "text": text,
                "direction": "inbound",
                "type": "SMS",
            },
        }
    }


@pytest.fixture()
def _sms_enabled():
    """Enable SMS in settings."""
    with patch("src.webhooks.server.settings") as mock_settings:
        mock_settings.webhook_secret = "test-secret"
        mock_settings.webhook_port = 8443
        mock_settings.telnyx_api_key = "test-telnyx-key"
        mock_settings.sms_owner_phone = "+15559876543"
        yield mock_settings


@pytest.fixture()
def _sms_disabled():
    """Disable SMS in settings."""
    with patch("src.webhooks.server.settings") as mock_settings:
        mock_settings.webhook_secret = "test-secret"
        mock_settings.webhook_port = 8443
        mock_settings.telnyx_api_key = ""
        mock_settings.sms_owner_phone = ""
        yield mock_settings


@pytest.fixture()
def _mock_sms_handler():
    """Mock the SMS handler."""
    with patch("src.webhooks.server._run_sms_handler", new_callable=AsyncMock) as mock:
        yield mock


async def test_sms_route_registered_when_enabled(_sms_enabled) -> None:
    """The /sms/inbound route should be registered when telnyx_api_key is set."""
    from src.webhooks.server import _create_web_app

    app = _create_web_app()
    routes = [
        r.resource.canonical for r in app.router.routes() if hasattr(r, "resource") and r.resource
    ]
    assert "/sms/inbound" in routes


async def test_sms_route_not_registered_when_disabled(_sms_disabled) -> None:
    """The /sms/inbound route should NOT be registered when telnyx_api_key is empty."""
    from src.webhooks.server import _create_web_app

    app = _create_web_app()
    routes = [
        r.resource.canonical for r in app.router.routes() if hasattr(r, "resource") and r.resource
    ]
    assert "/sms/inbound" not in routes


async def test_valid_inbound_sms(_sms_enabled, _mock_sms_handler) -> None:
    """Valid Telnyx payload returns 200 and fires handler."""
    from src.webhooks.server import _handle_sms_inbound

    payload = _telnyx_inbound_payload()

    request = AsyncMock()
    request.json = AsyncMock(return_value=payload)

    resp = await _handle_sms_inbound(request)
    assert resp.status == 200


async def test_delivery_report_filtered(_sms_enabled) -> None:
    """Non-message.received events should be filtered (200 but no handler call)."""
    from src.webhooks.server import _handle_sms_inbound

    payload = _telnyx_inbound_payload(event_type="message.finalized")

    request = AsyncMock()
    request.json = AsyncMock(return_value=payload)

    with patch("src.webhooks.server._run_sms_handler", new_callable=AsyncMock) as mock_handler:
        resp = await _handle_sms_inbound(request)

    assert resp.status == 200
    mock_handler.assert_not_awaited()


async def test_wrong_from_number_filtered(_sms_enabled) -> None:
    """SMS from wrong number returns 200 but handler is not fired."""
    from src.webhooks.server import _handle_sms_inbound

    payload = _telnyx_inbound_payload(from_number="+15551111111")

    request = AsyncMock()
    request.json = AsyncMock(return_value=payload)

    with patch("src.webhooks.server._run_sms_handler", new_callable=AsyncMock) as mock_handler:
        resp = await _handle_sms_inbound(request)

    assert resp.status == 200
    mock_handler.assert_not_awaited()


async def test_invalid_json_returns_400(_sms_enabled) -> None:
    """Invalid JSON should return 400."""
    from src.webhooks.server import _handle_sms_inbound

    request = AsyncMock()
    request.json = AsyncMock(side_effect=Exception("parse error"))

    resp = await _handle_sms_inbound(request)
    assert resp.status == 400


async def test_missing_from_number(_sms_enabled) -> None:
    """Missing from phone number returns 200 but no handler call."""
    from src.webhooks.server import _handle_sms_inbound

    payload = {
        "data": {
            "event_type": "message.received",
            "payload": {
                "from": {},
                "text": "Hello",
            },
        }
    }

    request = AsyncMock()
    request.json = AsyncMock(return_value=payload)

    with patch("src.webhooks.server._run_sms_handler", new_callable=AsyncMock) as mock_handler:
        resp = await _handle_sms_inbound(request)

    assert resp.status == 200
    mock_handler.assert_not_awaited()
