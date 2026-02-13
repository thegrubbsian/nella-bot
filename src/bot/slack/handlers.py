"""Slack message handlers with streaming responses."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any

from src.bot.session import get_session
from src.bot.slack.confirmations import request_confirmation
from src.llm.client import generate_response
from src.llm.models import MODEL_MAP, ModelManager, friendly
from src.memory.automatic import extract_and_save
from src.notifications.context import MessageContext

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Slack rate limits: ~1 message update per second per channel
STREAM_UPDATE_INTERVAL = 1.0


async def handle_message(
    event: dict[str, Any],
    say: Any,
    client: AsyncWebClient,
) -> None:
    """Handle an incoming DM message."""
    user_message = event.get("text", "")
    user_id = event["user"]
    channel_id = event["channel"]

    logger.info("Message from %s: %s", user_id, user_message[:80])

    session = get_session(channel_id)
    session.add("user", user_message)

    # Send placeholder
    resp = await say("...")
    msg_ts = resp["ts"]
    msg_channel = resp["channel"]
    last_edit = 0.0
    streamed_text = ""

    async def on_text_delta(delta: str) -> None:
        nonlocal streamed_text, last_edit
        streamed_text += delta
        now = time.monotonic()
        if now - last_edit >= STREAM_UPDATE_INTERVAL:
            with contextlib.suppress(Exception):
                await client.chat_update(
                    channel=msg_channel, ts=msg_ts, text=streamed_text,
                )
            last_edit = now

    msg_context = MessageContext(
        user_id=user_id,
        source_channel="slack",
        conversation_id=channel_id,
    )

    async def on_confirm(pending_tool: Any) -> bool:
        return await request_confirmation(
            client, channel_id=channel_id, pending_tool=pending_tool,
        )

    try:
        result_text = await generate_response(
            session.to_api_messages(),
            on_text_delta=on_text_delta,
            on_confirm=on_confirm,
            msg_context=msg_context,
        )

        if result_text:
            with contextlib.suppress(Exception):
                await client.chat_update(
                    channel=msg_channel, ts=msg_ts, text=result_text,
                )
            session.add("assistant", result_text)

            recent = session.to_api_messages()[-6:]
            asyncio.create_task(
                extract_and_save(
                    user_message=user_message,
                    assistant_response=result_text,
                    recent_history=recent,
                    conversation_id=channel_id,
                )
            )
        else:
            await client.chat_update(
                channel=msg_channel, ts=msg_ts, text="I got an empty response. Try again?",
            )

    except Exception:
        logger.exception("Error generating response")
        with contextlib.suppress(Exception):
            await client.chat_update(
                channel=msg_channel, ts=msg_ts, text="Something went wrong. Check the logs.",
            )


async def handle_clear_command(ack: Any, command: dict[str, Any], say: Any) -> None:
    """Handle /nella-clear — reset conversation history."""
    await ack()
    channel_id = command["channel_id"]
    session = get_session(channel_id)
    count = session.clear()
    await say(f"Cleared {count} messages. Starting fresh.")


async def handle_status_command(ack: Any, command: dict[str, Any], say: Any) -> None:
    """Handle /nella-status — show bot health info."""
    await ack()
    channel_id = command["channel_id"]
    session = get_session(channel_id)
    msg_count = len(session.messages)
    window = session.window_size
    mm = ModelManager.get()

    lines = [
        "*Nella Status*",
        f"Chat model: {friendly(mm.get_chat_model())}",
        f"Memory model: {friendly(mm.get_memory_model())}",
        f"Messages in context: {msg_count}/{window}",
        f"User: {command['user_id']}",
        "Status: online",
    ]
    await say("\n".join(lines))


async def handle_model_command(ack: Any, command: dict[str, Any], say: Any) -> None:
    """Handle /nella-model — view or switch the chat model."""
    await ack()
    mm = ModelManager.get()
    args = command.get("text", "").strip()

    if not args:
        lines = [
            f"Chat model: *{friendly(mm.get_chat_model())}*",
            f"Memory model: *{friendly(mm.get_memory_model())}*",
            f"Options: {', '.join(MODEL_MAP)}",
        ]
        await say("\n".join(lines))
        return

    name = args.lower()
    result = mm.set_chat_model(name)
    if not result:
        await say(f"Unknown model '{name}'. Valid options: {', '.join(MODEL_MAP)}")
        return

    lines = [
        f"Chat model → *{friendly(mm.get_chat_model())}*",
        f"Memory model: *{friendly(mm.get_memory_model())}*",
    ]
    await say("\n".join(lines))
