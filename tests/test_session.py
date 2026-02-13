"""Tests for in-memory conversation session."""

from src.bot.session import Session, get_session


def test_session_add_and_retrieve() -> None:
    """Messages should be stored and retrievable."""
    session = Session(window_size=10)
    session.add("user", "hello")
    session.add("assistant", "hi there")

    msgs = session.to_api_messages()
    assert len(msgs) == 2
    assert msgs[0] == {"role": "user", "content": "hello"}
    assert msgs[1] == {"role": "assistant", "content": "hi there"}


def test_session_sliding_window() -> None:
    """Session should trim to window_size."""
    session = Session(window_size=3)
    for i in range(5):
        session.add("user", f"msg {i}")

    msgs = session.to_api_messages()
    assert len(msgs) == 3
    assert msgs[0]["content"] == "msg 2"
    assert msgs[2]["content"] == "msg 4"


def test_session_clear() -> None:
    """Clear should remove all messages and return count."""
    session = Session(window_size=10)
    session.add("user", "hello")
    session.add("assistant", "hi")

    count = session.clear()
    assert count == 2
    assert session.to_api_messages() == []


def test_get_session_creates_and_reuses() -> None:
    """get_session should return the same session for the same chat_id."""
    s1 = get_session(99999)
    s2 = get_session(99999)
    assert s1 is s2

    s3 = get_session(88888)
    assert s3 is not s1


def test_get_session_string_key() -> None:
    """Slack DM channel IDs are strings."""
    s = get_session("D01ABC123")
    assert isinstance(s, Session)
    assert get_session("D01ABC123") is s
