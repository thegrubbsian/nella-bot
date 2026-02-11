"""Telegram inline-keyboard confirmation for tool calls.

When Claude invokes a tool that has ``requires_confirmation=True``, the
bot sends an inline-keyboard prompt (Approve / Deny) and waits for the
user to tap before allowing execution.
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

if TYPE_CHECKING:
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
    if inp.get("subject"):
        lines.append(f"Subject: {inp['subject']}")
    if inp.get("body"):
        lines.append(f"Body: {_trunc(inp['body'])}")
    return "\n".join(lines)


def _fmt_reply_to_email(inp: dict[str, Any]) -> str:
    lines = ["Reply to email"]
    if inp.get("message_id"):
        lines.append(f"Message ID: {inp['message_id']}")
    if inp.get("body"):
        lines.append(f"Body: {_trunc(inp['body'])}")
    return "\n".join(lines)


def _fmt_archive_email(inp: dict[str, Any]) -> str:
    mid = inp.get("message_id", "?")
    return f"Archive email\nMessage ID: {mid}"


def _fmt_archive_emails(inp: dict[str, Any]) -> str:
    ids = inp.get("message_ids", [])
    return f"Archive {len(ids)} email(s)\nMessage IDs: {', '.join(str(i) for i in ids)}"


def _fmt_create_event(inp: dict[str, Any]) -> str:
    lines = ["Create calendar event"]
    if inp.get("title"):
        lines.append(f"Title: {inp['title']}")
    if inp.get("start"):
        lines.append(f"Start: {inp['start']}")
    if inp.get("end"):
        lines.append(f"End: {inp['end']}")
    return "\n".join(lines)


def _fmt_update_event(inp: dict[str, Any]) -> str:
    lines = ["Update calendar event"]
    if inp.get("event_id"):
        lines.append(f"Event ID: {inp['event_id']}")
    return "\n".join(lines)


def _fmt_delete_event(inp: dict[str, Any]) -> str:
    eid = inp.get("event_id", "?")
    return f"Delete calendar event\nEvent ID: {eid}"


def _fmt_create_document(inp: dict[str, Any]) -> str:
    title = inp.get("title", "?")
    return f"Create document\nTitle: {title}"


def _fmt_update_document(inp: dict[str, Any]) -> str:
    lines = ["Update document"]
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
    return f"Delete file\nFile ID: {fid}"


def _fmt_schedule_task(inp: dict[str, Any]) -> str:
    lines = ["Schedule task"]
    if inp.get("name"):
        lines.append(f"Name: {inp['name']}")
    if inp.get("task_type"):
        lines.append(f"Type: {inp['task_type']}")
    if inp.get("action_type"):
        lines.append(f"Action: {inp['action_type']}")
    return "\n".join(lines)


def _fmt_cancel_scheduled_task(inp: dict[str, Any]) -> str:
    lines = ["Cancel scheduled task"]
    if inp.get("task_id"):
        lines.append(f"Task ID: {inp['task_id']}")
    if inp.get("search"):
        lines.append(f"Search: {inp['search']}")
    return "\n".join(lines)


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
    summary = format_tool_summary(
        pending_tool.tool_name,
        pending_tool.tool_input,
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
