"""Tests for the webhook HTTP server."""

from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

from src.webhooks.registry import webhook_registry
from src.webhooks.server import _create_web_app

TEST_SECRET = "test-secret-123"


# -- Helpers -----------------------------------------------------------------


class _FakeSettings:
    def __init__(
        self,
        webhook_secret: str = TEST_SECRET,
        webhook_port: int = 8443,
        telnyx_api_key: str = "",
        sms_owner_phone: str = "",
    ) -> None:
        self.webhook_secret = webhook_secret
        self.webhook_port = webhook_port
        self.telnyx_api_key = telnyx_api_key
        self.sms_owner_phone = sms_owner_phone


async def _make_client(app=None):
    """Create a TestClient for the webhook app."""
    app = app or _create_web_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


# -- Health check -----------------------------------------------------------


async def test_health_check() -> None:
    client = await _make_client()
    try:
        resp = await client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
    finally:
        await client.close()


# -- Auth -------------------------------------------------------------------


async def test_rejects_missing_secret() -> None:
    app = _create_web_app()
    with patch("src.webhooks.server.settings", _FakeSettings()):
        client = await _make_client(app)
        try:
            resp = await client.post("/webhooks/plaud", json={"test": True})
            assert resp.status == 401
        finally:
            await client.close()


async def test_rejects_wrong_secret() -> None:
    app = _create_web_app()
    with patch("src.webhooks.server.settings", _FakeSettings()):
        client = await _make_client(app)
        try:
            resp = await client.post(
                "/webhooks/plaud",
                json={"test": True},
                headers={"X-Webhook-Secret": "wrong"},
            )
            assert resp.status == 401
        finally:
            await client.close()


# -- Routing ----------------------------------------------------------------


async def test_unknown_source_returns_404() -> None:
    app = _create_web_app()
    with patch("src.webhooks.server.settings", _FakeSettings()):
        client = await _make_client(app)
        try:
            resp = await client.post(
                "/webhooks/nonexistent",
                json={"test": True},
                headers={"X-Webhook-Secret": TEST_SECRET},
            )
            assert resp.status == 404
        finally:
            await client.close()


async def test_valid_webhook_returns_200() -> None:
    handler = AsyncMock()
    old_get = webhook_registry.get

    def _mock_get(source: str):
        if source == "testsrc":
            return handler
        return old_get(source)

    app = _create_web_app()
    with (
        patch("src.webhooks.server.settings", _FakeSettings()),
        patch.object(webhook_registry, "get", side_effect=_mock_get),
    ):
        client = await _make_client(app)
        try:
            resp = await client.post(
                "/webhooks/testsrc",
                json={"key": "value"},
                headers={"X-Webhook-Secret": TEST_SECRET},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["ok"] is True
        finally:
            await client.close()


async def test_invalid_json_returns_400() -> None:
    handler = AsyncMock()
    old_get = webhook_registry.get

    def _mock_get(source: str):
        if source == "testsrc":
            return handler
        return old_get(source)

    app = _create_web_app()
    with (
        patch("src.webhooks.server.settings", _FakeSettings()),
        patch.object(webhook_registry, "get", side_effect=_mock_get),
    ):
        client = await _make_client(app)
        try:
            resp = await client.post(
                "/webhooks/testsrc",
                data=b"not json",
                headers={
                    "X-Webhook-Secret": TEST_SECRET,
                    "Content-Type": "application/json",
                },
            )
            assert resp.status == 400
        finally:
            await client.close()


# -- WebhookServer lifecycle ------------------------------------------------


async def test_server_skips_start_without_secret() -> None:
    from src.webhooks.server import WebhookServer

    with patch("src.webhooks.server.settings", _FakeSettings(webhook_secret="")):
        server = WebhookServer(port=9999)
        await server.start()
        assert server._runner is None
        await server.stop()
