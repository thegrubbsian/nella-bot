"""Tests for src/bot/confirmations."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.telegram.confirmations import (
    _action_label,
    _enrich_cancel_task,
    _humanize_cron,
    _humanize_datetime,
    _pending,
    format_tool_summary,
    generate_confirmation_id,
    get_pending,
    request_confirmation,
    resolve_confirmation,
)
from src.llm.client import PendingToolCall
from src.scheduler.models import ScheduledTask

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
    assert "Reply to email" in text
    assert "msg123" not in text
    assert "Thanks!" in text


def test_format_archive_email() -> None:
    text = format_tool_summary("archive_email", {"message_id": "m1"}, "Archive")
    assert "Archive 1 email" in text
    assert "m1" not in text


def test_format_archive_emails() -> None:
    text = format_tool_summary("archive_emails", {"message_ids": ["a", "b"]}, "Archive")
    assert "2 email" in text


def test_format_create_event() -> None:
    inp = {
        "title": "Standup",
        "start_time": "2025-01-01T09:00",
        "end_time": "2025-01-01T09:30",
    }
    text = format_tool_summary("create_event", inp, "Create event")
    assert "Standup" in text
    assert "Jan 1, 2025" in text
    assert "9:00 AM" in text


def test_format_delete_event() -> None:
    text = format_tool_summary("delete_event", {"event_id": "ev1"}, "Delete")
    assert "ev1" in text


def test_format_create_document() -> None:
    text = format_tool_summary("create_document", {"title": "Notes"}, "Create doc")
    assert "Create Google Doc" in text
    assert "Notes" in text


def test_format_delete_file() -> None:
    text = format_tool_summary("delete_file", {"file_id": "f1"}, "Delete file")
    assert "Trash Drive file" in text
    assert "f1" in text


def test_format_schedule_task() -> None:
    inp = {
        "name": "Morning check",
        "task_type": "one_off",
        "action_type": "ai_task",
        "run_at": "2025-06-01T15:00:00-06:00",
        "action_content": "Check my inbox",
    }
    text = format_tool_summary("schedule_task", inp, "Schedule")
    assert "Schedule one-time task" in text
    assert "Morning check" in text
    assert "AI task (with tool access)" in text
    assert "Jun 1, 2025" in text
    assert "Check my inbox" in text


def test_format_cancel_scheduled_task() -> None:
    text = format_tool_summary("cancel_scheduled_task", {"task_id": "t1"}, "Cancel")
    assert "Cancel scheduled task" in text
    assert "t1" in text


def test_format_cancel_scheduled_task_search() -> None:
    text = format_tool_summary(
        "cancel_scheduled_task", {"search_query": "morning"}, "Cancel"
    )
    assert "Search: morning" in text


def test_format_cancel_scheduled_task_enriched() -> None:
    inp = {
        "task_id": "abc123",
        "_task_name": "Morning check",
        "_task_type": "recurring",
        "_task_schedule": {"cron": "0 8 * * *"},
        "_task_action_type": "ai_task",
        "_task_next_run_at": "2025-06-02T08:00:00-06:00",
    }
    text = format_tool_summary("cancel_scheduled_task", inp, "Cancel")
    assert "Name: Morning check" in text
    assert "Daily at 8:00 AM" in text
    assert "AI task (with tool access)" in text
    assert "Next run:" in text
    assert "Jun 2, 2025" in text
    # Raw ID should NOT appear when enriched
    assert "abc123" not in text


def test_format_cancel_scheduled_task_enriched_one_off() -> None:
    inp = {
        "task_id": "abc123",
        "_task_name": "Reminder",
        "_task_type": "one_off",
        "_task_schedule": {"run_at": "2025-06-01T15:00:00"},
        "_task_action_type": "simple_message",
    }
    text = format_tool_summary("cancel_scheduled_task", inp, "Cancel")
    assert "Name: Reminder" in text
    assert "Jun 1, 2025" in text
    assert "Reminder message" in text


# -- _enrich_cancel_task ---------------------------------------------------


async def test_enrich_cancel_task() -> None:
    task = ScheduledTask(
        id="task123",
        name="Daily triage",
        task_type="recurring",
        schedule={"cron": "0 9 * * 1-5"},
        action={"type": "ai_task", "prompt": "Check inbox"},
        next_run_at="2025-06-02T09:00:00-06:00",
    )
    mock_store = AsyncMock()
    mock_store.get_task = AsyncMock(return_value=task)

    with patch("src.scheduler.store.TaskStore.get", return_value=mock_store):
        result = await _enrich_cancel_task({"task_id": "task123"})

    assert result["_task_name"] == "Daily triage"
    assert result["_task_type"] == "recurring"
    assert result["_task_schedule"] == {"cron": "0 9 * * 1-5"}
    assert result["_task_action_type"] == "ai_task"
    assert result["_task_next_run_at"] == "2025-06-02T09:00:00-06:00"
    assert result["task_id"] == "task123"


async def test_enrich_cancel_task_missing() -> None:
    mock_store = AsyncMock()
    mock_store.get_task = AsyncMock(return_value=None)

    with patch("src.scheduler.store.TaskStore.get", return_value=mock_store):
        result = await _enrich_cancel_task({"task_id": "nonexistent"})

    assert "_task_name" not in result
    assert result["task_id"] == "nonexistent"


async def test_enrich_cancel_task_dashed_uuid() -> None:
    """Enricher strips dashes from UUIDs that Claude reformats."""
    task = ScheduledTask(
        id="6e79f4b7c1dc4ce080c6eaa496b13dca",
        name="Morning check",
        task_type="recurring",
        schedule={"cron": "0 8 * * *"},
        action={"type": "ai_task", "prompt": "Check inbox"},
    )
    mock_store = AsyncMock()
    mock_store.get_task = AsyncMock(return_value=task)

    with patch("src.scheduler.store.TaskStore.get", return_value=mock_store):
        result = await _enrich_cancel_task(
            {"task_id": "6e79f4b7-c1dc-4ce0-80c6-eaa496b13dca"}
        )

    assert result["_task_name"] == "Morning check"
    # Verify the store was called with the normalized (dashless) ID
    mock_store.get_task.assert_awaited_once_with("6e79f4b7c1dc4ce080c6eaa496b13dca")


async def test_enrich_cancel_task_no_id() -> None:
    result = await _enrich_cancel_task({"search_query": "morning"})
    assert result == {"search_query": "morning"}


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


# -- _humanize_cron --------------------------------------------------------


def test_humanize_cron_daily() -> None:
    assert _humanize_cron("0 8 * * *") == "Daily at 8:00 AM"


def test_humanize_cron_daily_pm() -> None:
    assert _humanize_cron("30 14 * * *") == "Daily at 2:30 PM"


def test_humanize_cron_weekdays() -> None:
    assert _humanize_cron("0 9 * * 1-5") == "Weekdays at 9:00 AM"


def test_humanize_cron_weekends() -> None:
    assert _humanize_cron("0 10 * * 0,6") == "Weekends at 10:00 AM"


def test_humanize_cron_every_n_minutes() -> None:
    assert _humanize_cron("*/15 * * * *") == "Every 15 minutes"


def test_humanize_cron_every_n_hours() -> None:
    assert _humanize_cron("0 */2 * * *") == "Every 2 hours"


def test_humanize_cron_fallback() -> None:
    expr = "0 8 1 * *"
    assert _humanize_cron(expr) == expr


def test_humanize_cron_invalid() -> None:
    assert _humanize_cron("not a cron") == "not a cron"


# -- _humanize_datetime ----------------------------------------------------


def test_humanize_datetime_naive() -> None:
    result = _humanize_datetime("2025-06-01T15:00:00")
    assert "Jun 1, 2025" in result
    assert "3:00 PM" in result


def test_humanize_datetime_with_tz() -> None:
    result = _humanize_datetime("2025-06-01T15:00:00-06:00")
    assert "Jun 1, 2025" in result
    assert "3:00 PM" in result


def test_humanize_datetime_fallback() -> None:
    assert _humanize_datetime("not-a-date") == "not-a-date"


# -- _action_label ---------------------------------------------------------


def test_action_label_ai_task() -> None:
    assert _action_label("ai_task") == "AI task (with tool access)"


def test_action_label_simple_message() -> None:
    assert _action_label("simple_message") == "Reminder message"


def test_action_label_unknown() -> None:
    assert _action_label("custom_thing") == "custom_thing"


# -- New formatter tests ---------------------------------------------------


def test_format_send_email_with_cc_and_attachments() -> None:
    inp = {
        "to": "alice@example.com",
        "cc": "bob@example.com",
        "subject": "Hi",
        "body": "Hello",
        "attachments": ["report.pdf", "data.csv"],
    }
    text = format_tool_summary("send_email", inp, "Send")
    assert "CC: bob@example.com" in text
    assert "Attachments: 2 file(s)" in text


def test_format_reply_to_email_with_attachments() -> None:
    inp = {"message_id": "m1", "body": "Here you go", "attachments": ["file.pdf"]}
    text = format_tool_summary("reply_to_email", inp, "Reply")
    assert "Attachments: 1 file(s)" in text


def test_format_create_event_with_location_and_attendees() -> None:
    inp = {
        "title": "Lunch",
        "start_time": "2025-03-15T12:00",
        "end_time": "2025-03-15T13:00",
        "location": "Downtown Cafe",
        "attendees": ["alice@example.com", "bob@example.com"],
    }
    text = format_tool_summary("create_event", inp, "Create")
    assert "Location: Downtown Cafe" in text
    assert "alice@example.com" in text


def test_format_update_event_shows_changed_fields() -> None:
    inp = {
        "event_id": "ev1",
        "title": "New Title",
        "start_time": "2025-03-15T14:00",
    }
    text = format_tool_summary("update_event", inp, "Update")
    assert "New Title" in text
    assert "Mar 15, 2025" in text


def test_format_update_document_header() -> None:
    inp = {"document_id": "doc1", "content": "New content"}
    text = format_tool_summary("update_document", inp, "Update")
    assert "Replace document content" in text


def test_format_schedule_task_recurring() -> None:
    inp = {
        "name": "Daily Email Triage",
        "task_type": "recurring",
        "cron": "0 8 * * *",
        "action_type": "ai_task",
        "action_content": "Check my inbox for urgent emails",
    }
    text = format_tool_summary("schedule_task", inp, "Schedule")
    assert "Schedule recurring task" in text
    assert "Daily at 8:00 AM" in text
    assert "AI task (with tool access)" in text
    assert "Check my inbox" in text


def test_format_schedule_task_simple_message() -> None:
    inp = {
        "name": "Drink water",
        "task_type": "recurring",
        "cron": "0 */2 * * *",
        "action_type": "simple_message",
        "action_content": "Time to drink some water!",
    }
    text = format_tool_summary("schedule_task", inp, "Schedule")
    assert "Reminder message" in text
    assert "Every 2 hours" in text


def test_format_linkedin_create_post_visibility() -> None:
    inp = {"text": "Hello LinkedIn!", "visibility": "PUBLIC"}
    text = format_tool_summary("linkedin_create_post", inp, "Post")
    assert "Public (anyone)" in text


def test_format_linkedin_create_post_connections() -> None:
    inp = {"text": "Hello!", "visibility": "CONNECTIONS"}
    text = format_tool_summary("linkedin_create_post", inp, "Post")
    assert "Connections only" in text


def test_format_upload_to_drive() -> None:
    inp = {"path": "report.pdf", "folder_id": "folder123", "filename": "Q1 Report.pdf"}
    text = format_tool_summary("upload_to_drive", inp, "Upload")
    assert "Upload file to Google Drive" in text
    assert "Q1 Report.pdf" in text
    assert "folder123" in text


def test_format_upload_to_drive_no_filename() -> None:
    inp = {"path": "report.pdf"}
    text = format_tool_summary("upload_to_drive", inp, "Upload")
    assert "report.pdf" in text


def test_format_create_contact() -> None:
    inp = {
        "given_name": "Alice",
        "family_name": "Smith",
        "email": "alice@example.com",
        "phone": "+1234567890",
        "organization": "Acme Corp",
    }
    text = format_tool_summary("create_contact", inp, "Create")
    assert "Create contact" in text
    assert "Alice Smith" in text
    assert "alice@example.com" in text
    assert "+1234567890" in text
    assert "Acme Corp" in text


def test_format_update_contact() -> None:
    inp = {
        "resource_name": "people/c123",
        "email": "new@example.com",
        "phone": "+1111111111",
    }
    text = format_tool_summary("update_contact", inp, "Update")
    assert "Update contact" in text
    assert "people/c123" in text
    assert "email" in text
    assert "phone" in text


def test_format_scratch_wipe() -> None:
    text = format_tool_summary("scratch_wipe", {}, "Wipe")
    assert "Wipe scratch space" in text
    assert "ALL temporary files" in text


def test_format_browse_web() -> None:
    inp = {"url": "https://example.com", "task": "Find contact info"}
    text = format_tool_summary("browse_web", inp, "Browse")
    assert "Browse website" in text
    assert "https://example.com" in text
    assert "Find contact info" in text


def test_format_delete_note() -> None:
    text = format_tool_summary("delete_note", {"note_id": 42}, "Delete")
    assert "Delete note" in text
    assert "42" in text


# -- resolve_confirmation ---------------------------------------------------


def test_resolve_sets_future_true() -> None:
    loop = asyncio.new_event_loop()
    future: asyncio.Future[bool] = loop.create_future()
    from src.bot.telegram.confirmations import PendingConfirmation

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
    from src.bot.telegram.confirmations import PendingConfirmation

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
    from src.bot.telegram.confirmations import PendingConfirmation

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
