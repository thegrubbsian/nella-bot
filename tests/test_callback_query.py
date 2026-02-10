"""Tests for handle_callback_query in src/bot/handlers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock

from src.bot.confirmations import PendingConfirmation, _pending
from src.bot.handlers import handle_callback_query

# -- Helpers -----------------------------------------------------------------


def _make_update(callback_data: str) -> MagicMock:
    """Build a minimal mock Update with a CallbackQuery."""
    query = MagicMock()
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    # query.message.text is read when editing
    msg = MagicMock()
    type(msg).text = PropertyMock(return_value="**Confirm action:**\nSend email")
    query.message = msg

    update = MagicMock()
    update.callback_query = query
    return update


def _make_context() -> MagicMock:
    return MagicMock()


def _inject_pending(conf_id: str, *, done: bool = False) -> asyncio.Future[bool]:
    """Place a PendingConfirmation in the module-level dict."""
    loop = asyncio.get_event_loop()
    future: asyncio.Future[bool] = loop.create_future()
    if done:
        future.set_result(True)
    _pending[conf_id] = PendingConfirmation(
        id=conf_id,
        chat_id=123,
        tool_name="send_email",
        description="Send an email",
        future=future,
    )
    return future


# -- Tests -------------------------------------------------------------------


async def test_approve_resolves_future_true() -> None:
    future = _inject_pending("ab12cd34")
    try:
        update = _make_update("cfm:ab12cd34:y")
        await handle_callback_query(update, _make_context())

        assert future.result() is True
        query = update.callback_query
        query.answer.assert_awaited_once_with("Approved")
        query.edit_message_text.assert_awaited_once()
        edited_text = query.edit_message_text.call_args.kwargs["text"]
        assert "Approved" in edited_text
    finally:
        _pending.pop("ab12cd34", None)


async def test_deny_resolves_future_false() -> None:
    future = _inject_pending("11223344")
    try:
        update = _make_update("cfm:11223344:n")
        await handle_callback_query(update, _make_context())

        assert future.result() is False
        query = update.callback_query
        query.answer.assert_awaited_once_with("Denied")
    finally:
        _pending.pop("11223344", None)


async def test_expired_confirmation() -> None:
    # No pending entry for this ID
    update = _make_update("cfm:deadbeef:y")
    await handle_callback_query(update, _make_context())

    query = update.callback_query
    query.answer.assert_awaited_once_with("This confirmation has expired.")


async def test_non_cfm_data_ignored() -> None:
    update = _make_update("other:data")
    await handle_callback_query(update, _make_context())

    query = update.callback_query
    query.answer.assert_awaited_once()
    # No args means just an acknowledgement
    query.answer.assert_awaited_once_with()


async def test_already_resolved() -> None:
    _inject_pending("aabbccdd", done=True)
    try:
        update = _make_update("cfm:aabbccdd:y")
        await handle_callback_query(update, _make_context())

        query = update.callback_query
        query.answer.assert_awaited_once_with("Already handled.")
    finally:
        _pending.pop("aabbccdd", None)


async def test_invalid_callback_data_format() -> None:
    update = _make_update("cfm:toofewparts")
    await handle_callback_query(update, _make_context())

    query = update.callback_query
    query.answer.assert_awaited_once_with("Invalid callback data.")
