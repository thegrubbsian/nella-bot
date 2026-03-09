"""Tests for inbound Slack DM handler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.slack.handler import _clean_slack_text, handle_inbound_slack_dm

# ---------------------------------------------------------------------------
# _clean_slack_text tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<@U12345> hello", "hello"),
        ("<@U12345> <@UABCDE> hi", "hi"),
        ("<https://example.com|Example>", "Example"),
        ("<https://example.com>", "https://example.com"),
        ("<#C123|general>", "#general"),
        ("A &amp; B &lt; C &gt; D", "A & B < C > D"),
        ("  spaces  ", "spaces"),
        ("plain text", "plain text"),
    ],
)
def test_clean_slack_text(raw: str, expected: str) -> None:
    assert _clean_slack_text(raw) == expected


def test_clean_slack_text_combined() -> None:
    raw = "<@U123> Check <https://example.com|this> &amp; <https://foo.com>"
    result = _clean_slack_text(raw)
    assert result == "Check this & https://foo.com"


# ---------------------------------------------------------------------------
# handle_inbound_slack_dm tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_pipeline():
    """Mock the full handler pipeline."""
    with (
        patch("src.slack.handler.get_session") as mock_get_session,
        patch("src.slack.handler.generate_response", new_callable=AsyncMock) as mock_gen,
        patch("src.slack.handler.send_slack_message", new_callable=AsyncMock) as mock_send,
        patch("src.slack.handler.extract_and_save", new_callable=AsyncMock),
    ):
        mock_session = MagicMock()
        mock_session.to_api_messages.return_value = [
            {"role": "user", "content": "hello"},
        ]
        mock_get_session.return_value = mock_session
        mock_gen.return_value = "Hi there!"
        mock_send.return_value = True

        yield {
            "get_session": mock_get_session,
            "generate_response": mock_gen,
            "send_slack_message": mock_send,
            "session": mock_session,
        }


async def test_full_pipeline(mock_pipeline) -> None:
    """Happy path: message processed and response sent."""
    await handle_inbound_slack_dm("personal", "U123", "D456", "hello")

    mock_pipeline["get_session"].assert_called_once_with("slack:personal:U123")
    mock_pipeline["generate_response"].assert_called_once()
    mock_pipeline["send_slack_message"].assert_called_once_with(
        "D456", "Hi there!", workspace="personal", thread_ts=None
    )


async def test_empty_text_ignored(mock_pipeline) -> None:
    """Empty text after cleaning is silently ignored."""
    await handle_inbound_slack_dm("personal", "U123", "D456", "   ")
    mock_pipeline["generate_response"].assert_not_called()


async def test_mentions_only_ignored(mock_pipeline) -> None:
    """A message that's just a mention is empty after cleaning."""
    await handle_inbound_slack_dm("personal", "U123", "D456", "<@UBOT>")
    mock_pipeline["generate_response"].assert_not_called()


async def test_thread_ts_passed(mock_pipeline) -> None:
    """thread_ts is forwarded to the reply."""
    await handle_inbound_slack_dm(
        "personal", "U123", "D456", "hello", thread_ts="1234.5678"
    )
    mock_pipeline["send_slack_message"].assert_called_once_with(
        "D456", "Hi there!", workspace="personal", thread_ts="1234.5678"
    )


async def test_msg_context_correct(mock_pipeline) -> None:
    """MessageContext is built correctly."""
    await handle_inbound_slack_dm("work", "U789", "D999", "test msg")

    call_kwargs = mock_pipeline["generate_response"].call_args
    ctx = call_kwargs.kwargs.get("msg_context") or call_kwargs[1].get("msg_context")
    assert ctx.user_id == "U789"
    assert ctx.source_channel == "slack"
    assert ctx.conversation_id == "slack:work:U789"
    assert ctx.metadata["workspace"] == "work"
    assert ctx.metadata["channel"] == "D999"


async def test_empty_response(mock_pipeline) -> None:
    """Empty LLM response sends fallback message."""
    mock_pipeline["generate_response"].return_value = ""
    await handle_inbound_slack_dm("personal", "U123", "D456", "hello")

    call_args = mock_pipeline["send_slack_message"].call_args
    assert "empty response" in call_args[0][1].lower()


async def test_error_handling(mock_pipeline) -> None:
    """Errors are caught and an error message is sent."""
    mock_pipeline["generate_response"].side_effect = RuntimeError("boom")
    await handle_inbound_slack_dm("personal", "U123", "D456", "hello")

    call_args = mock_pipeline["send_slack_message"].call_args
    assert "something went wrong" in call_args[0][1].lower()
