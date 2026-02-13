"""Telegram inline-keyboard confirmation for tool calls.

When Claude invokes a tool that has ``requires_confirmation=True``, the
bot sends an inline-keyboard prompt (Approve / Deny) and waits for the
user to tap before allowing execution.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from telegram import Bot

    from src.llm.client import PendingToolCall

logger = logging.getLogger(__name__)

# Default timeout before auto-denying a confirmation (seconds)
DEFAULT_TIMEOUT = 120.0


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PendingConfirmation:
    """An in-flight confirmation prompt waiting for the user to respond."""

    id: str
    chat_id: int
    tool_name: str
    description: str
    future: asyncio.Future[bool]
    message_id: int | None = None
    created_at: float = field(default_factory=time.monotonic)


# Module-level dict of pending confirmations keyed by confirmation ID.
_pending: dict[str, PendingConfirmation] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def generate_confirmation_id() -> str:
    """Return an 8-character hex string suitable for callback data."""
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _humanize_cron(expr: str) -> str:
    """Convert common cron expressions to plain English, fallback to raw."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return expr

    minute, hour, dom, month, dow = parts

    # "0 8 * * *" → "Daily at 8:00 AM"
    if dom == "*" and month == "*" and dow == "*" and minute.isdigit() and hour.isdigit():
        return f"Daily at {_fmt_time(int(hour), int(minute))}"

    # "0 9 * * 1-5" → "Weekdays at 9:00 AM"
    if dom == "*" and month == "*" and dow == "1-5" and minute.isdigit() and hour.isdigit():
        return f"Weekdays at {_fmt_time(int(hour), int(minute))}"

    # "0 9 * * 0,6" → "Weekends at 9:00 AM"
    if (
        dom == "*" and month == "*" and dow in ("0,6", "6,0")
        and minute.isdigit() and hour.isdigit()
    ):
        return f"Weekends at {_fmt_time(int(hour), int(minute))}"

    # "*/N * * * *" → "Every N minutes"
    m = re.match(r"^\*/(\d+)$", minute)
    if m and hour == "*" and dom == "*" and month == "*" and dow == "*":
        n = int(m.group(1))
        return f"Every {n} minute{'s' if n != 1 else ''}"

    # "0 */N * * *" → "Every N hours"
    m = re.match(r"^\*/(\d+)$", hour)
    if m and minute == "0" and dom == "*" and month == "*" and dow == "*":
        n = int(m.group(1))
        return f"Every {n} hour{'s' if n != 1 else ''}"

    return expr


def _fmt_time(hour: int, minute: int) -> str:
    """Format hour/minute as 12-hour time like '8:00 AM'."""
    period = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {period}"


def _humanize_datetime(iso: str) -> str:
    """Parse ISO 8601 string to 'Feb 13, 2026 at 2:00 PM' (with tz if present)."""
    try:
        dt = datetime.fromisoformat(iso)
        formatted = dt.strftime("%b %-d, %Y at %-I:%M %p")
        if dt.tzinfo is not None:
            formatted += f" {dt.strftime('%Z') or dt.strftime('%z')}"
        return formatted
    except (ValueError, TypeError):
        return iso


def _action_label(action_type: str) -> str:
    """Translate action_type to a human-friendly label."""
    labels = {
        "ai_task": "AI task (with tool access)",
        "simple_message": "Reminder message",
    }
    return labels.get(action_type, action_type)


# ---------------------------------------------------------------------------
# Tool-specific formatters
# ---------------------------------------------------------------------------

_MAX_BODY = 200  # Truncation limit for large text fields


def _trunc(text: str, limit: int = _MAX_BODY) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _fmt_send_email(inp: dict[str, Any]) -> str:
    lines = ["Send email"]
    if inp.get("to"):
        lines.append(f"To: {inp['to']}")
    if inp.get("cc"):
        lines.append(f"CC: {inp['cc']}")
    if inp.get("subject"):
        lines.append(f"Subject: {inp['subject']}")
    if inp.get("body"):
        lines.append(f"Body: {_trunc(inp['body'])}")
    attachments = inp.get("attachments") or []
    if attachments:
        lines.append(f"Attachments: {len(attachments)} file(s)")
    return "\n".join(lines)


def _fmt_reply_to_email(inp: dict[str, Any]) -> str:
    lines = ["Reply to email"]
    if inp.get("body"):
        lines.append(f"Body: {_trunc(inp['body'])}")
    attachments = inp.get("attachments") or []
    if attachments:
        lines.append(f"Attachments: {len(attachments)} file(s)")
    return "\n".join(lines)


def _fmt_archive_email(inp: dict[str, Any]) -> str:
    return "Archive 1 email"


def _fmt_archive_emails(inp: dict[str, Any]) -> str:
    ids = inp.get("message_ids", [])
    return f"Archive {len(ids)} email(s)"


def _fmt_create_event(inp: dict[str, Any]) -> str:
    lines = ["Create calendar event"]
    if inp.get("title"):
        lines.append(f"Title: {inp['title']}")
    if inp.get("start_time"):
        lines.append(f"Start: {_humanize_datetime(inp['start_time'])}")
    if inp.get("end_time"):
        lines.append(f"End: {_humanize_datetime(inp['end_time'])}")
    if inp.get("location"):
        lines.append(f"Location: {inp['location']}")
    if inp.get("attendees"):
        lines.append(f"Attendees: {', '.join(inp['attendees'])}")
    return "\n".join(lines)


def _fmt_update_event(inp: dict[str, Any]) -> str:
    lines = ["Update calendar event"]
    if inp.get("title"):
        lines.append(f"Title: {inp['title']}")
    if inp.get("start_time"):
        lines.append(f"Start: {_humanize_datetime(inp['start_time'])}")
    if inp.get("end_time"):
        lines.append(f"End: {_humanize_datetime(inp['end_time'])}")
    if inp.get("location"):
        lines.append(f"Location: {inp['location']}")
    if inp.get("attendees"):
        lines.append(f"Attendees: {', '.join(inp['attendees'])}")
    return "\n".join(lines)


def _fmt_delete_event(inp: dict[str, Any]) -> str:
    eid = inp.get("event_id", "?")
    return f"Delete calendar event\nEvent ID: {eid}"


def _fmt_create_document(inp: dict[str, Any]) -> str:
    lines = ["Create Google Doc"]
    title = inp.get("title", "?")
    lines.append(f"Title: {title}")
    if inp.get("content"):
        lines.append(f"Content: {_trunc(inp['content'])}")
    return "\n".join(lines)


def _fmt_update_document(inp: dict[str, Any]) -> str:
    lines = ["Replace document content"]
    if inp.get("document_id"):
        lines.append(f"Document ID: {inp['document_id']}")
    if inp.get("content"):
        lines.append(f"Content: {_trunc(inp['content'])}")
    return "\n".join(lines)


def _fmt_append_to_document(inp: dict[str, Any]) -> str:
    lines = ["Append to document"]
    if inp.get("document_id"):
        lines.append(f"Document ID: {inp['document_id']}")
    if inp.get("content"):
        lines.append(f"Content: {_trunc(inp['content'])}")
    return "\n".join(lines)


def _fmt_delete_file(inp: dict[str, Any]) -> str:
    fid = inp.get("file_id", "?")
    return f"Trash Drive file\nFile ID: {fid}"


def _fmt_schedule_task(inp: dict[str, Any]) -> str:
    task_type = inp.get("task_type", "")
    header = "Schedule recurring task" if task_type == "recurring" else "Schedule one-time task"
    lines = [header]
    if inp.get("name"):
        lines.append(f"Name: {inp['name']}")
    # Build a human-readable schedule line
    if task_type == "recurring" and inp.get("cron"):
        lines.append(f"Schedule: {_humanize_cron(inp['cron'])}")
    elif task_type == "one_off" and inp.get("run_at"):
        lines.append(f"Run at: {_humanize_datetime(inp['run_at'])}")
    if inp.get("action_type"):
        lines.append(f"Action: {_action_label(inp['action_type'])}")
    if inp.get("action_content"):
        lines.append(f"Instructions: {_trunc(inp['action_content'], 150)}")
    if inp.get("description"):
        lines.append(f"Description: {_trunc(inp['description'], 100)}")
    return "\n".join(lines)


def _fmt_cancel_scheduled_task(inp: dict[str, Any]) -> str:
    lines = ["Cancel scheduled task"]
    if inp.get("_task_name"):
        lines.append(f"Name: {inp['_task_name']}")
        task_type = inp.get("_task_type", "")
        schedule = inp.get("_task_schedule", {})
        if task_type == "recurring" and schedule.get("cron"):
            lines.append(f"Schedule: {_humanize_cron(schedule['cron'])}")
        elif task_type == "one_off" and schedule.get("run_at"):
            lines.append(f"Run at: {_humanize_datetime(schedule['run_at'])}")
        if inp.get("_task_action_type"):
            lines.append(f"Action: {_action_label(inp['_task_action_type'])}")
    elif inp.get("task_id"):
        lines.append(f"Task ID: {inp['task_id']}")
    if inp.get("search_query"):
        lines.append(f"Search: {inp['search_query']}")
    return "\n".join(lines)


_VISIBILITY_LABELS = {
    "PUBLIC": "Public (anyone)",
    "CONNECTIONS": "Connections only",
}


def _fmt_linkedin_create_post(inp: dict[str, Any]) -> str:
    lines = ["Create LinkedIn post"]
    vis = inp.get("visibility", "PUBLIC")
    lines.append(f"Visibility: {_VISIBILITY_LABELS.get(vis, vis)}")
    if inp.get("text"):
        lines.append(f"Text: {_trunc(inp['text'])}")
    return "\n".join(lines)


def _fmt_linkedin_post_comment(inp: dict[str, Any]) -> str:
    lines = ["Comment on LinkedIn post"]
    if inp.get("post_url"):
        lines.append(f"Post: {inp['post_url']}")
    if inp.get("text"):
        lines.append(f"Comment: {_trunc(inp['text'])}")
    return "\n".join(lines)


def _fmt_upload_to_drive(inp: dict[str, Any]) -> str:
    lines = ["Upload file to Google Drive"]
    filename = inp.get("filename") or inp.get("path", "?")
    lines.append(f"File: {filename}")
    if inp.get("folder_id"):
        lines.append(f"Destination folder: {inp['folder_id']}")
    return "\n".join(lines)


def _fmt_create_contact(inp: dict[str, Any]) -> str:
    lines = ["Create contact"]
    name_parts = [inp.get("given_name", ""), inp.get("family_name", "")]
    name = " ".join(p for p in name_parts if p).strip()
    if name:
        lines.append(f"Name: {name}")
    if inp.get("email"):
        lines.append(f"Email: {inp['email']}")
    if inp.get("phone"):
        lines.append(f"Phone: {inp['phone']}")
    if inp.get("organization"):
        lines.append(f"Company: {inp['organization']}")
    return "\n".join(lines)


def _fmt_update_contact(inp: dict[str, Any]) -> str:
    lines = ["Update contact"]
    if inp.get("resource_name"):
        lines.append(f"Contact: {inp['resource_name']}")
    changed: list[str] = []
    for fld in ("given_name", "family_name", "email", "phone", "organization", "title"):
        if inp.get(fld) is not None:
            changed.append(fld.replace("_", " "))
    if changed:
        lines.append(f"Updating: {', '.join(changed)}")
    return "\n".join(lines)


def _fmt_scratch_wipe(inp: dict[str, Any]) -> str:
    return "Wipe scratch space\nThis will delete ALL temporary files"


def _fmt_browse_web(inp: dict[str, Any]) -> str:
    lines = ["Browse website"]
    if inp.get("url"):
        lines.append(f"URL: {inp['url']}")
    if inp.get("task"):
        lines.append(f"Task: {_trunc(inp['task'], 150)}")
    return "\n".join(lines)


def _fmt_delete_note(inp: dict[str, Any]) -> str:
    note_id = inp.get("note_id", "?")
    return f"Delete note\nNote ID: {note_id}"


_TOOL_FORMATTERS: dict[str, Any] = {
    "send_email": _fmt_send_email,
    "reply_to_email": _fmt_reply_to_email,
    "archive_email": _fmt_archive_email,
    "archive_emails": _fmt_archive_emails,
    "create_event": _fmt_create_event,
    "update_event": _fmt_update_event,
    "delete_event": _fmt_delete_event,
    "create_document": _fmt_create_document,
    "update_document": _fmt_update_document,
    "append_to_document": _fmt_append_to_document,
    "delete_file": _fmt_delete_file,
    "schedule_task": _fmt_schedule_task,
    "cancel_scheduled_task": _fmt_cancel_scheduled_task,
    "linkedin_create_post": _fmt_linkedin_create_post,
    "linkedin_post_comment": _fmt_linkedin_post_comment,
    "upload_to_drive": _fmt_upload_to_drive,
    "create_contact": _fmt_create_contact,
    "update_contact": _fmt_update_contact,
    "scratch_wipe": _fmt_scratch_wipe,
    "browse_web": _fmt_browse_web,
    "delete_note": _fmt_delete_note,
}


# ---------------------------------------------------------------------------
# Async enrichers — augment tool_input with display fields before formatting
# ---------------------------------------------------------------------------


async def _enrich_cancel_task(inp: dict[str, Any]) -> dict[str, Any]:
    """Look up task details by ID for display in confirmation."""
    task_id = inp.get("task_id")
    if not task_id:
        return inp
    try:
        from src.scheduler.store import TaskStore

        store = TaskStore.get()
        task = await store.get_task(task_id)
    except Exception:
        return inp
    if task is None:
        return inp
    return {
        **inp,
        "_task_name": task.name,
        "_task_type": task.task_type,
        "_task_schedule": task.schedule,
        "_task_action_type": task.action_type,
    }


_ENRICHERS: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "cancel_scheduled_task": _enrich_cancel_task,
}


def format_tool_summary(tool_name: str, tool_input: dict[str, Any], description: str) -> str:
    """Return a human-readable summary for a pending tool call."""
    formatter = _TOOL_FORMATTERS.get(tool_name)
    if formatter:
        return formatter(tool_input)
    # Generic fallback
    import json

    params = _trunc(json.dumps(tool_input, default=str), _MAX_BODY)
    return f"{tool_name}\n{description}\nParams: {params}"


# ---------------------------------------------------------------------------
# Core confirmation flow
# ---------------------------------------------------------------------------


def get_pending(confirmation_id: str) -> PendingConfirmation | None:
    """Look up a pending confirmation by ID."""
    return _pending.get(confirmation_id)


def resolve_confirmation(confirmation_id: str, *, approved: bool) -> bool:
    """Resolve a pending confirmation.

    Returns True if the confirmation was found and resolved, False if it
    was already resolved or expired.
    """
    pc = _pending.get(confirmation_id)
    if pc is None:
        return False
    if pc.future.done():
        return False
    pc.future.set_result(approved)
    return True


async def request_confirmation(
    bot: Bot,
    chat_id: int,
    pending_tool: PendingToolCall,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """Send an inline-keyboard confirmation and wait for the user's tap.

    Returns True if the user approved, False on deny or timeout.
    """
    conf_id = generate_confirmation_id()

    tool_input = pending_tool.tool_input
    enricher = _ENRICHERS.get(pending_tool.tool_name)
    if enricher:
        tool_input = await enricher(tool_input)

    summary = format_tool_summary(
        pending_tool.tool_name,
        tool_input,
        pending_tool.description,
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Approve", callback_data=f"cfm:{conf_id}:y"),
            InlineKeyboardButton("Deny", callback_data=f"cfm:{conf_id}:n"),
        ]
    ])

    safe_summary = html.escape(summary)
    msg = await bot.send_message(
        chat_id=chat_id,
        text=f"<b>Confirm action:</b>\n{safe_summary}",
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()

    pc = PendingConfirmation(
        id=conf_id,
        chat_id=chat_id,
        tool_name=pending_tool.tool_name,
        description=pending_tool.description,
        future=future,
        message_id=msg.message_id,
    )
    _pending[conf_id] = pc

    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except TimeoutError:
        logger.info("Confirmation %s timed out", conf_id)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg.message_id,
                text=f"<b>Confirm action:</b> (timed out)\n{safe_summary}",
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("Could not edit timed-out confirmation message", exc_info=True)
        return False
    finally:
        _pending.pop(conf_id, None)
