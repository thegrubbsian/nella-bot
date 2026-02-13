"""Tests for Slack tool confirmations."""

import asyncio
from unittest.mock import AsyncMock

from src.bot.slack.confirmations import (
    _pending,
    get_pending,
    request_confirmation,
    resolve_confirmation,
)
from src.llm.client import PendingToolCall


def _make_pending_tool(
    name: str = "send_email",
    tool_input: dict | None = None,
    description: str = "Send an email",
) -> PendingToolCall:
    return PendingToolCall(
        tool_use_id="toolu_abc123",
        tool_name=name,
        tool_input=tool_input or {},
        description=description,
    )


def _make_mock_client() -> AsyncMock:
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(
        return_value={"ts": "1234567890.123456", "channel": "D01ABC123"}
    )
    client.chat_update = AsyncMock()
    return client


def test_resolve_sets_future_true() -> None:
    loop = asyncio.new_event_loop()
    future: asyncio.Future[bool] = loop.create_future()
    from src.bot.slack.confirmations import PendingConfirmation

    pc = PendingConfirmation(
        id="aabb1122",
        channel_id="D01ABC123",
        tool_name="send_email",
        description="d",
        future=future,
    )
    _pending["aabb1122"] = pc
    try:
        ok = resolve_confirmation("aabb1122", approved=True)
        assert ok is True
        assert future.result() is True
    finally:
        _pending.pop("aabb1122", None)
        loop.close()


def test_resolve_sets_future_false() -> None:
    loop = asyncio.new_event_loop()
    future: asyncio.Future[bool] = loop.create_future()
    from src.bot.slack.confirmations import PendingConfirmation

    pc = PendingConfirmation(
        id="cc112233",
        channel_id="D01ABC123",
        tool_name="send_email",
        description="d",
        future=future,
    )
    _pending["cc112233"] = pc
    try:
        ok = resolve_confirmation("cc112233", approved=False)
        assert ok is True
        assert future.result() is False
    finally:
        _pending.pop("cc112233", None)
        loop.close()


def test_resolve_unknown_id_returns_false() -> None:
    assert resolve_confirmation("nonexistent", approved=True) is False


def test_get_pending_returns_none_for_missing() -> None:
    assert get_pending("nope") is None


async def test_request_approved() -> None:
    client = _make_mock_client()
    pending_tool = _make_pending_tool(
        tool_input={"to": "a@b.com", "subject": "Hi", "body": "Hello"}
    )

    async def _approve_soon():
        await asyncio.sleep(0.05)
        for cid, pc in list(_pending.items()):
            if pc.tool_name == "send_email":
                resolve_confirmation(cid, approved=True)
                break

    task = asyncio.create_task(_approve_soon())
    result = await request_confirmation(client, channel_id="D01ABC123", pending_tool=pending_tool)
    await task

    assert result is True
    client.chat_postMessage.assert_awaited_once()


async def test_request_denied() -> None:
    client = _make_mock_client()
    pending_tool = _make_pending_tool(name="delete_event", tool_input={"event_id": "e1"})

    async def _deny_soon():
        await asyncio.sleep(0.05)
        for cid, pc in list(_pending.items()):
            if pc.tool_name == "delete_event":
                resolve_confirmation(cid, approved=False)
                break

    task = asyncio.create_task(_deny_soon())
    result = await request_confirmation(client, channel_id="D01ABC123", pending_tool=pending_tool)
    await task

    assert result is False


async def test_request_timeout_returns_false() -> None:
    client = _make_mock_client()
    pending_tool = _make_pending_tool()

    result = await request_confirmation(
        client, channel_id="D01ABC123", pending_tool=pending_tool, timeout=0.05,
    )
    assert result is False
    client.chat_update.assert_awaited_once()
