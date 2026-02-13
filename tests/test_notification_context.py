"""Tests for MessageContext dataclass."""

from src.notifications.context import MessageContext

# -- Defaults ----------------------------------------------------------------


def test_reply_channel_defaults_to_source() -> None:
    ctx = MessageContext(user_id="123", source_channel="telegram")
    assert ctx.reply_channel == "telegram"


def test_conversation_id_defaults_to_user_id() -> None:
    ctx = MessageContext(user_id="456", source_channel="sms")
    assert ctx.conversation_id == "456"


def test_metadata_defaults_to_empty_dict() -> None:
    ctx = MessageContext(user_id="1", source_channel="telegram")
    assert ctx.metadata == {}


# -- Explicit overrides ------------------------------------------------------


def test_explicit_reply_channel() -> None:
    ctx = MessageContext(user_id="1", source_channel="sms", reply_channel="telegram")
    assert ctx.source_channel == "sms"
    assert ctx.reply_channel == "telegram"


def test_explicit_conversation_id() -> None:
    ctx = MessageContext(user_id="1", source_channel="telegram", conversation_id="conv-99")
    assert ctx.conversation_id == "conv-99"


def test_metadata_passed_through() -> None:
    ctx = MessageContext(
        user_id="1",
        source_channel="telegram",
        metadata={"chat_id": "789", "thread_id": "42"},
    )
    assert ctx.metadata["chat_id"] == "789"
    assert ctx.metadata["thread_id"] == "42"


# -- All fields set ----------------------------------------------------------


def test_all_fields_explicit() -> None:
    ctx = MessageContext(
        user_id="u1",
        source_channel="sms",
        reply_channel="telegram",
        conversation_id="c1",
        metadata={"key": "val"},
    )
    assert ctx.user_id == "u1"
    assert ctx.source_channel == "sms"
    assert ctx.reply_channel == "telegram"
    assert ctx.conversation_id == "c1"
    assert ctx.metadata == {"key": "val"}
