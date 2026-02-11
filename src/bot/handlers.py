"""Telegram message handlers with streaming responses."""

import asyncio
import contextlib
import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

from src.bot.confirmations import get_pending, request_confirmation, resolve_confirmation
from src.bot.security import is_allowed
from src.bot.session import get_session
from src.llm.client import generate_response
from src.llm.models import MODEL_MAP, ModelManager, friendly
from src.memory.automatic import extract_and_save
from src.notifications.context import MessageContext

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
    mm = ModelManager.get()

    lines = [
        "**Nella Status**",
        f"Chat model: {friendly(mm.get_chat_model())}",
        f"Memory model: {friendly(mm.get_memory_model())}",
        f"Messages in context: {msg_count}/{window}",
        f"User: {update.effective_user.id}",
        "Status: online",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /model — view or switch the chat model."""
    if not is_allowed(update):
        return

    mm = ModelManager.get()
    args = context.args

    if not args:
        lines = [
            f"Chat model: **{friendly(mm.get_chat_model())}**",
            f"Memory model: **{friendly(mm.get_memory_model())}**",
            f"Options: {', '.join(MODEL_MAP)}",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    name = args[0].lower()
    result = mm.set_chat_model(name)
    if not result:
        await update.message.reply_text(
            f"Unknown model '{name}'. Valid options: {', '.join(MODEL_MAP)}"
        )
        return

    lines = [
        f"Chat model → **{friendly(mm.get_chat_model())}**",
        f"Memory model: **{friendly(mm.get_memory_model())}**",
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

    msg_context = MessageContext(
        user_id=str(update.effective_user.id),
        source_channel="telegram",
        conversation_id=str(chat_id),
    )

    async def on_confirm(pending_tool):
        return await request_confirmation(
            bot=context.bot, chat_id=chat_id, pending_tool=pending_tool,
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


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline-keyboard callbacks for tool confirmations."""
    query = update.callback_query
    data = query.data or ""

    if not data.startswith("cfm:"):
        await query.answer()
        return

    parts = data.split(":")
    if len(parts) != 3:
        await query.answer("Invalid callback data.")
        return

    _, conf_id, choice = parts
    pc = get_pending(conf_id)

    if pc is None:
        await query.answer("This confirmation has expired.")
        with contextlib.suppress(Exception):
            await query.edit_message_text(
                text=query.message.text + "\n\n(expired)",
            )
        return

    if pc.future.done():
        await query.answer("Already handled.")
        return

    approved = choice == "y"
    resolve_confirmation(conf_id, approved=approved)

    status = "Approved" if approved else "Denied"
    with contextlib.suppress(Exception):
        await query.edit_message_text(
            text=query.message.text + f"\n\n→ {status}",
        )
    await query.answer(status)
