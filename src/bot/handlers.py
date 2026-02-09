"""Telegram message handlers with streaming responses."""

import asyncio
import contextlib
import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

from src.bot.security import is_allowed
from src.bot.session import get_session
from src.llm.client import generate_response
from src.memory.automatic import extract_and_save

logger = logging.getLogger(__name__)

# Minimum interval between Telegram message edits (seconds)
STREAM_UPDATE_INTERVAL = 0.5


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — greet the user."""
    if not is_allowed(update):
        return

    await update.message.reply_text(
        "Hey! I'm Nella, your personal assistant. What can I help you with?"
    )


async def handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear — reset conversation history."""
    if not is_allowed(update):
        return

    session = get_session(update.effective_chat.id)
    count = session.clear()
    await update.message.reply_text(f"Cleared {count} messages. Starting fresh.")


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status — show bot health info."""
    if not is_allowed(update):
        return

    session = get_session(update.effective_chat.id)
    msg_count = len(session.messages)
    window = session.window_size

    lines = [
        "**Nella Status**",
        f"Messages in context: {msg_count}/{window}",
        f"User: {update.effective_user.id}",
        "Status: online",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages with streaming Claude response."""
    if not is_allowed(update):
        return

    user_message = update.message.text
    chat_id = update.effective_chat.id

    logger.info("Message from %s: %s", chat_id, user_message[:80])

    session = get_session(chat_id)
    session.add("user", user_message)

    # Send a placeholder that we'll edit as the stream arrives
    reply = await update.message.reply_text("...")
    last_edit = 0.0
    streamed_text = ""

    async def on_text_delta(delta: str) -> None:
        """Called for each text chunk from Claude."""
        nonlocal streamed_text, last_edit
        streamed_text += delta
        now = time.monotonic()
        if now - last_edit >= STREAM_UPDATE_INTERVAL:
            with contextlib.suppress(Exception):
                await reply.edit_text(streamed_text)
            last_edit = now

    try:
        result_text = await generate_response(
            session.to_api_messages(),
            on_text_delta=on_text_delta,
        )

        if result_text:
            with contextlib.suppress(Exception):
                await reply.edit_text(result_text)
            session.add("assistant", result_text)

            # Background memory extraction (don't block the response)
            recent = session.to_api_messages()[-6:]  # last 3 exchanges
            asyncio.create_task(
                extract_and_save(
                    user_message=user_message,
                    assistant_response=result_text,
                    recent_history=recent,
                    conversation_id=str(chat_id),
                )
            )
        else:
            await reply.edit_text("I got an empty response. Try again?")

    except Exception:
        logger.exception("Error generating response")
        with contextlib.suppress(Exception):
            await reply.edit_text("Something went wrong. Check the logs.")

    # Small delay to avoid Telegram rate limits between conversations
    await asyncio.sleep(0.1)
