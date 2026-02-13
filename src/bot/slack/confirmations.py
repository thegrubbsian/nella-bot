"""Slack Block Kit confirmation for tool calls.

When Claude invokes a tool that has ``requires_confirmation=True``, the
bot sends a Block Kit message with Approve / Deny buttons and waits for
the user to click before allowing execution.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

    from src.llm.client import PendingToolCall

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120.0


@dataclass
class PendingConfirmation:
    """An in-flight confirmation prompt waiting for the user to respond."""

    id: str
    channel_id: str
    tool_name: str
    description: str
    future: asyncio.Future[bool]
    message_ts: str | None = None
    created_at: float = field(default_factory=time.monotonic)


_pending: dict[str, PendingConfirmation] = {}


def generate_confirmation_id() -> str:
    """Return an 8-character hex string suitable for action IDs."""
    return uuid.uuid4().hex[:8]


def get_pending(confirmation_id: str) -> PendingConfirmation | None:
    """Look up a pending confirmation by ID."""
    return _pending.get(confirmation_id)


def resolve_confirmation(confirmation_id: str, *, approved: bool) -> bool:
    """Resolve a pending confirmation.

    Returns True if the confirmation was found and resolved, False otherwise.
    """
    pc = _pending.get(confirmation_id)
    if pc is None:
        return False
    if pc.future.done():
        return False
    pc.future.set_result(approved)
    return True


async def request_confirmation(
    client: AsyncWebClient,
    channel_id: str,
    pending_tool: PendingToolCall,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """Send a Block Kit confirmation and wait for the user's click.

    Returns True if the user approved, False on deny or timeout.
    """
    from src.bot.telegram.confirmations import format_tool_summary

    conf_id = generate_confirmation_id()
    summary = format_tool_summary(
        pending_tool.tool_name,
        pending_tool.tool_input,
        pending_tool.description,
    )

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Confirm action:*\n{summary}"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": f"cfm:{conf_id}:y",
                    "value": "approve",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Deny"},
                    "style": "danger",
                    "action_id": f"cfm:{conf_id}:n",
                    "value": "deny",
                },
            ],
        },
    ]

    resp = await client.chat_postMessage(
        channel=channel_id,
        text=f"Confirm action: {summary}",
        blocks=blocks,
    )

    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()

    pc = PendingConfirmation(
        id=conf_id,
        channel_id=channel_id,
        tool_name=pending_tool.tool_name,
        description=pending_tool.description,
        future=future,
        message_ts=resp.get("ts"),
    )
    _pending[conf_id] = pc

    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except TimeoutError:
        logger.info("Confirmation %s timed out", conf_id)
        try:
            await client.chat_update(
                channel=channel_id,
                ts=resp["ts"],
                text=f"Confirm action: (timed out)\n{summary}",
                blocks=[],
            )
        except Exception:
            logger.debug("Could not edit timed-out confirmation message", exc_info=True)
        return False
    finally:
        _pending.pop(conf_id, None)
