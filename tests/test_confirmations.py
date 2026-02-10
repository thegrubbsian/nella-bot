"""Tests for src/bot/confirmations."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.bot.confirmations import (
    _pending,
    format_tool_summary,
    generate_confirmation_id,
    get_pending,
    request_confirmation,
    resolve_confirmation,
)
from src.llm.client import PendingToolCall

# -- Helpers -----------------------------------------------------------------


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


def _make_mock_bot() -> AsyncMock:
    """Create a mock telegram.Bot with send_message returning a Message."""
    bot = AsyncMock()
    msg = MagicMock()
    msg.message_id = 42
    bot.send_message = AsyncMock(return_value=msg)
    bot.edit_message_text = AsyncMock()
    return bot


# -- generate_confirmation_id -----------------------------------------------


def test_id_length() -> None:
    cid = generate_confirmation_id()
    assert len(cid) == 8


def test_id_is_hex() -> None:
    cid = generate_confirmation_id()
    int(cid, 16)  # Raises ValueError if not valid hex


def test_ids_are_unique() -> None:
    ids = {generate_confirmation_id() for _ in range(100)}
    assert len(ids) == 100


# -- format_tool_summary ----------------------------------------------------


def test_format_send_email() -> None:
    inp = {"to": "alice@example.com", "subject": "Hi", "body": "Hello there"}
    text = format_tool_summary("send_email", inp, "Send an email")
    assert "alice@example.com" in text
    assert "Hi" in text
    assert "Hello there" in text


def test_format_reply_to_email() -> None:
    inp = {"message_id": "msg123", "body": "Thanks!"}
    text = format_tool_summary("reply_to_email", inp, "Reply")
    assert "msg123" in text
    assert "Thanks!" in text


def test_format_archive_email() -> None:
    text = format_tool_summary("archive_email", {"message_id": "m1"}, "Archive")
    assert "m1" in text


def test_format_archive_emails() -> None:
    text = format_tool_summary("archive_emails", {"message_ids": ["a", "b"]}, "Archive")
    assert "2 email" in text


def test_format_create_event() -> None:
    inp = {"title": "Standup", "start": "2025-01-01T09:00", "end": "2025-01-01T09:30"}
    text = format_tool_summary("create_event", inp, "Create event")
    assert "Standup" in text
    assert "2025-01-01T09:00" in text


def test_format_delete_event() -> None:
    text = format_tool_summary("delete_event", {"event_id": "ev1"}, "Delete")
    assert "ev1" in text


def test_format_create_document() -> None:
    text = format_tool_summary("create_document", {"title": "Notes"}, "Create doc")
    assert "Notes" in text


def test_format_delete_file() -> None:
    text = format_tool_summary("delete_file", {"file_id": "f1"}, "Delete file")
    assert "f1" in text


def test_format_schedule_task() -> None:
    inp = {"name": "Morning check", "task_type": "one_off", "action_type": "ai_task"}
    text = format_tool_summary("schedule_task", inp, "Schedule")
    assert "Morning check" in text


def test_format_cancel_scheduled_task() -> None:
    text = format_tool_summary("cancel_scheduled_task", {"task_id": "t1"}, "Cancel")
    assert "t1" in text


def test_format_unknown_tool_fallback() -> None:
    inp = {"key": "value"}
    text = format_tool_summary("unknown_tool", inp, "Does something")
    assert "unknown_tool" in text
    assert "Does something" in text
    assert "key" in text


def test_format_truncates_long_body() -> None:
    long_body = "x" * 500
    inp = {"to": "a@b.com", "subject": "S", "body": long_body}
    text = format_tool_summary("send_email", inp, "Send")
    assert "…" in text
    assert len(text) < 500


# -- resolve_confirmation ---------------------------------------------------


def test_resolve_sets_future_true() -> None:
    loop = asyncio.new_event_loop()
    future: asyncio.Future[bool] = loop.create_future()
    from src.bot.confirmations import PendingConfirmation

    pc = PendingConfirmation(
        id="aabb1122",
        chat_id=1,
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
    from src.bot.confirmations import PendingConfirmation

    pc = PendingConfirmation(
        id="cc112233",
        chat_id=1,
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


def test_resolve_already_done_returns_false() -> None:
    loop = asyncio.new_event_loop()
    future: asyncio.Future[bool] = loop.create_future()
    future.set_result(True)
    from src.bot.confirmations import PendingConfirmation

    pc = PendingConfirmation(
        id="dd445566",
        chat_id=1,
        tool_name="send_email",
        description="d",
        future=future,
    )
    _pending["dd445566"] = pc
    try:
        assert resolve_confirmation("dd445566", approved=False) is False
    finally:
        _pending.pop("dd445566", None)
        loop.close()


# -- get_pending ------------------------------------------------------------


def test_get_pending_returns_none_for_missing() -> None:
    assert get_pending("nope") is None


# -- request_confirmation ---------------------------------------------------


async def test_request_approved() -> None:
    bot = _make_mock_bot()
    pending_tool = _make_pending_tool(
        tool_input={"to": "a@b.com", "subject": "Hi", "body": "Hello"}
    )

    async def _approve_soon():
        await asyncio.sleep(0.05)
        # Find the pending confirmation and approve it
        for cid, pc in list(_pending.items()):
            if pc.tool_name == "send_email":
                resolve_confirmation(cid, approved=True)
                break

    task = asyncio.create_task(_approve_soon())
    result = await request_confirmation(bot, chat_id=123, pending_tool=pending_tool)
    await task

    assert result is True
    bot.send_message.assert_awaited_once()


async def test_request_denied() -> None:
    bot = _make_mock_bot()
    pending_tool = _make_pending_tool(name="delete_event", tool_input={"event_id": "e1"})

    async def _deny_soon():
        await asyncio.sleep(0.05)
        for cid, pc in list(_pending.items()):
            if pc.tool_name == "delete_event":
                resolve_confirmation(cid, approved=False)
                break

    task = asyncio.create_task(_deny_soon())
    result = await request_confirmation(bot, chat_id=123, pending_tool=pending_tool)
    await task

    assert result is False


async def test_request_timeout_returns_false() -> None:
    bot = _make_mock_bot()
    pending_tool = _make_pending_tool()

    result = await request_confirmation(
        bot, chat_id=123, pending_tool=pending_tool, timeout=0.05,
    )
    assert result is False
    # Timed out confirmation should have been edited
    bot.edit_message_text.assert_awaited_once()


async def test_request_cleans_up_after_timeout() -> None:
    bot = _make_mock_bot()
    pending_tool = _make_pending_tool()
    before = len(_pending)

    await request_confirmation(
        bot, chat_id=123, pending_tool=pending_tool, timeout=0.05,
    )
    assert len(_pending) == before  # Cleaned up
