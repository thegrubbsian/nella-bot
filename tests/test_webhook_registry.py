"""Tests for the webhook handler registry."""

from src.webhooks.registry import WebhookRegistry

# -- Registration ------------------------------------------------------------


def test_register_handler() -> None:
    reg = WebhookRegistry()

    @reg.handler("plaud")
    async def handle_plaud(payload: dict) -> None:
        pass

    assert "plaud" in reg.sources
    assert reg.get("plaud") is handle_plaud


def test_unknown_source_returns_none() -> None:
    reg = WebhookRegistry()
    assert reg.get("nope") is None


def test_sources_lists_all_registered() -> None:
    reg = WebhookRegistry()

    @reg.handler("a")
    async def handle_a(payload: dict) -> None:
        pass

    @reg.handler("b")
    async def handle_b(payload: dict) -> None:
        pass

    assert sorted(reg.sources) == ["a", "b"]


def test_sources_empty_initially() -> None:
    reg = WebhookRegistry()
    assert reg.sources == []
