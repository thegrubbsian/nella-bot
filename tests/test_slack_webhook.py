"""Tests for the Slack Events webhook route."""

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.webhooks.server import _handle_slack_events, _verify_slack_signature

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIGNING_SECRET = "test-secret-abc"


def _sign(
    body: bytes,
    signing_secret: str = SIGNING_SECRET,
    timestamp: str | None = None,
) -> tuple[str, str]:
    """Generate Slack signing headers for a request body."""
    ts = timestamp or str(int(time.time()))
    basestring = f"v0:{ts}:{body.decode('utf-8')}"
    sig = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return ts, sig


def _slack_dm_event(
    user: str = "U123USER",
    channel: str = "D456DM",
    text: str = "hello nella",
    team_id: str = "T12345",
    subtype: str | None = None,
) -> dict:
    """Build a Slack Events API DM payload."""
    event: dict = {
        "type": "message",
        "channel_type": "im",
        "user": user,
        "channel": channel,
        "text": text,
        "ts": "1234567890.123456",
    }
    if subtype:
        event["subtype"] = subtype

    return {
        "type": "event_callback",
        "team_id": team_id,
        "event": event,
    }


@pytest.fixture()
def mock_mgr():
    """Build a mock SlackAuthManager instance."""
    mgr = MagicMock()
    mgr.signing_secret = SIGNING_SECRET
    mgr.bot_user_id = "UBOT"
    mgr.workspace = "personal"
    return mgr


@pytest.fixture()
def _slack_enabled(mock_mgr):
    """Patch SlackAuthManager for webhook tests."""
    with patch(
        "src.integrations.slack_auth.SlackAuthManager.get_by_team_id",
        return_value=mock_mgr,
    ):
        yield


def _make_request(payload: dict, signing_secret: str = SIGNING_SECRET) -> AsyncMock:
    """Build a mock aiohttp.Request with signed Slack headers."""
    body = json.dumps(payload).encode("utf-8")
    ts, sig = _sign(body, signing_secret)

    request = AsyncMock()
    request.read = AsyncMock(return_value=body)
    request.json = AsyncMock(return_value=payload)
    request.headers = {
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
    }
    return request


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_verify_signature_valid() -> None:
    body = b'{"test": true}'
    ts = str(int(time.time()))
    basestring = f"v0:{ts}:{body.decode('utf-8')}"
    sig = "v0=" + hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert _verify_slack_signature(body, ts, sig, SIGNING_SECRET) is True


def test_verify_signature_invalid() -> None:
    body = b'{"test": true}'
    ts = str(int(time.time()))
    assert _verify_slack_signature(body, ts, "v0=badsig", SIGNING_SECRET) is False


# ---------------------------------------------------------------------------
# URL verification challenge
# ---------------------------------------------------------------------------


async def test_url_verification() -> None:
    """Slack's url_verification challenge should be echoed back."""
    payload = {"type": "url_verification", "challenge": "abc123challenge"}
    request = AsyncMock()
    request.read = AsyncMock(return_value=json.dumps(payload).encode())
    request.json = AsyncMock(return_value=payload)

    resp = await _handle_slack_events(request)
    body = json.loads(resp.body)
    assert body["challenge"] == "abc123challenge"


# ---------------------------------------------------------------------------
# Valid DM event
# ---------------------------------------------------------------------------


async def test_valid_dm_event(_slack_enabled) -> None:
    """A valid DM event fires the handler."""
    payload = _slack_dm_event()
    request = _make_request(payload)

    with patch("src.webhooks.server._run_slack_handler", new_callable=AsyncMock):
        resp = await _handle_slack_events(request)

    assert resp.status == 200


async def test_bot_self_message_filtered(_slack_enabled, mock_mgr) -> None:
    """Messages from the bot itself should be ignored."""
    payload = _slack_dm_event(user="UBOT")
    request = _make_request(payload)

    with patch("src.webhooks.server._run_slack_handler", new_callable=AsyncMock) as mock_handler:
        resp = await _handle_slack_events(request)

    assert resp.status == 200
    mock_handler.assert_not_awaited()


async def test_non_im_event_ignored(_slack_enabled) -> None:
    """Messages in channels (not DMs) should be ignored."""
    payload = _slack_dm_event()
    payload["event"]["channel_type"] = "channel"
    request = _make_request(payload)

    with patch("src.webhooks.server._run_slack_handler", new_callable=AsyncMock) as mock_handler:
        resp = await _handle_slack_events(request)

    assert resp.status == 200
    mock_handler.assert_not_awaited()


async def test_subtype_filtered(_slack_enabled) -> None:
    """Messages with a subtype (edits, joins, etc.) should be ignored."""
    payload = _slack_dm_event(subtype="message_changed")
    request = _make_request(payload)

    with patch("src.webhooks.server._run_slack_handler", new_callable=AsyncMock) as mock_handler:
        resp = await _handle_slack_events(request)

    assert resp.status == 200
    mock_handler.assert_not_awaited()


async def test_invalid_signature_rejected(_slack_enabled) -> None:
    """Invalid signature should return 401."""
    payload = _slack_dm_event()
    body = json.dumps(payload).encode("utf-8")

    request = AsyncMock()
    request.read = AsyncMock(return_value=body)
    request.json = AsyncMock(return_value=payload)
    request.headers = {
        "X-Slack-Request-Timestamp": str(int(time.time())),
        "X-Slack-Signature": "v0=invalidsignature",
    }

    resp = await _handle_slack_events(request)
    assert resp.status == 401


async def test_unknown_team_rejected() -> None:
    """Unknown team_id returns 403."""
    payload = _slack_dm_event(team_id="TUNKNOWN")
    body = json.dumps(payload).encode("utf-8")

    request = AsyncMock()
    request.read = AsyncMock(return_value=body)
    request.json = AsyncMock(return_value=payload)
    request.headers = {}

    with patch(
        "src.integrations.slack_auth.SlackAuthManager.get_by_team_id",
        return_value=None,
    ):
        resp = await _handle_slack_events(request)

    assert resp.status == 403


async def test_route_registration() -> None:
    """Slack route should be registered when enabled."""
    with (
        patch("src.webhooks.server.settings") as mock_settings,
        patch("src.integrations.slack_auth.SlackAuthManager.any_enabled", return_value=True),
    ):
        mock_settings.telnyx_api_key = ""
        mock_settings.webhook_secret = ""

        from src.webhooks.server import _create_web_app

        app = _create_web_app()
        routes = [
            r.resource.canonical
            for r in app.router.routes()
            if hasattr(r, "resource") and r.resource
        ]
        assert "/slack/events" in routes


async def test_route_not_registered_when_disabled() -> None:
    """Slack route should NOT be registered when disabled."""
    with (
        patch("src.webhooks.server.settings") as mock_settings,
        patch("src.integrations.slack_auth.SlackAuthManager.any_enabled", return_value=False),
    ):
        mock_settings.telnyx_api_key = ""
        mock_settings.webhook_secret = ""

        from src.webhooks.server import _create_web_app

        app = _create_web_app()
        routes = [
            r.resource.canonical
            for r in app.router.routes()
            if hasattr(r, "resource") and r.resource
        ]
        assert "/slack/events" not in routes
