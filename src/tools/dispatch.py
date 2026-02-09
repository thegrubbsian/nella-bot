"""Tool dispatch — routes Claude tool calls to implementations."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from src.integrations.calendar import create_event, get_todays_events, get_upcoming_events
from src.integrations.gmail import get_recent_emails, send_email
from src.memory.semantic import recall, remember

logger = logging.getLogger(__name__)

_HANDLERS: dict[str, Any] = {
    "get_todays_events": get_todays_events,
    "get_upcoming_events": get_upcoming_events,
    "create_event": create_event,
    "get_recent_emails": get_recent_emails,
    "send_email": send_email,
    "remember": remember,
    "recall": recall,
}


async def dispatch_tool_call(name: str, arguments: dict[str, Any]) -> str:
    """Execute a tool by name with the given arguments.

    Args:
        name: The tool name from Claude's tool_use block.
        arguments: The parsed arguments dict.

    Returns:
        JSON string of the tool result.
    """
    if name == "get_current_time":
        return json.dumps({"time": datetime.now(UTC).isoformat()})

    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        result = await handler(**arguments)
        return json.dumps(result, default=str)
    except Exception:
        logger.exception("Tool %s failed", name)
        return json.dumps({"error": f"Tool '{name}' failed. Check logs for details."})
