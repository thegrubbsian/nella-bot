"""Tests for generate_response() — text retraction and error handling."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic

from src.llm.client import generate_response
from src.tools.base import ToolResult
from src.tools.registry import ToolDef

# ---------------------------------------------------------------------------
# Helpers: mock the streaming API
# ---------------------------------------------------------------------------


@dataclass
class _FakeBlock:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] | None = None


class _FakeStream:
    """Simulates an anthropic streaming context manager."""

    def __init__(self, text_chunks: list[str], content_blocks: list[_FakeBlock]) -> None:
        self._text_chunks = text_chunks
        self._content_blocks = content_blocks

    @property
    async def text_stream(self):
        for chunk in self._text_chunks:
            yield chunk

    async def get_final_message(self):
        msg = MagicMock()
        msg.content = self._content_blocks
        msg.stop_reason = "end_turn" if not any(
            b.type == "tool_use" for b in self._content_blocks
        ) else "tool_use"
        return msg


def _make_stream(text: str, blocks: list[_FakeBlock]) -> _FakeStream:
    """Build a fake stream that yields text in a single chunk."""
    return _FakeStream([text] if text else [], blocks)


def _make_mock_client(rounds: list[_FakeStream]):
    """Create a mock Anthropic client that returns a sequence of streaming rounds."""
    client = MagicMock()
    call_count = 0

    @asynccontextmanager
    async def _stream(**kwargs):
        nonlocal call_count
        yield rounds[call_count]
        call_count += 1

    client.messages.stream = _stream
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_confirmation_text_retracted_from_result() -> None:
    """Text from confirmation rounds is streamed (for real-time UX) but
    retracted from full_text so the final result is clean."""
    # Round 1: Claude says "Done!" and calls a confirmation tool
    round1 = _make_stream(
        "All done, I cancelled those!",
        [
            _FakeBlock(type="text", text="All done, I cancelled those!"),
            _FakeBlock(
                type="tool_use",
                id="tool1",
                name="cancel_scheduled_task",
                input={"task_id": "abc123"},
            ),
        ],
    )
    # Round 2: Claude generates accurate text after seeing tool result
    round2 = _make_stream(
        "Tasks have been cancelled.",
        [_FakeBlock(type="text", text="Tasks have been cancelled.")],
    )

    mock_client = _make_mock_client([round1, round2])

    tool_def = ToolDef(
        name="cancel_scheduled_task",
        description="Cancel a task",
        category="scheduler",
        handler=AsyncMock(return_value=ToolResult(data={"cancelled": True})),
        requires_confirmation=True,
    )

    streamed: list[str] = []

    async def on_text_delta(text: str) -> None:
        streamed.append(text)

    async def on_confirm(pending) -> bool:
        return True

    mock_registry = MagicMock()
    mock_registry.get_schemas.return_value = [{"name": "cancel_scheduled_task"}]
    mock_registry.get.return_value = tool_def
    mock_registry.execute = AsyncMock(
        return_value=ToolResult(data={"cancelled": True})
    )

    with (
        patch("src.llm.client._get_client", return_value=mock_client),
        patch("src.llm.client.build_system_prompt", new_callable=AsyncMock, return_value="system"),
        patch("src.llm.client.registry", mock_registry),
    ):
        result = await generate_response(
            [{"role": "user", "content": "cancel my tasks"}],
            on_text_delta=on_text_delta,
            on_confirm=on_confirm,
        )

    # Text WAS streamed (for real-time display) — both rounds
    full_streamed = "".join(streamed)
    assert "All done" in full_streamed
    assert "Tasks have been cancelled." in full_streamed

    # But the return value (used for final message edit + history) is clean
    assert "All done" not in result
    assert "Tasks have been cancelled." in result


async def test_model_param_overrides_default() -> None:
    """When model is passed, it's used instead of ModelManager default."""
    round1 = _make_stream(
        "Hello!",
        [_FakeBlock(type="text", text="Hello!")],
    )

    mock_client = _make_mock_client([round1])

    mock_registry = MagicMock()
    mock_registry.get_schemas.return_value = []

    captured_kwargs: list[dict] = []
    original_stream = mock_client.messages.stream

    @asynccontextmanager
    async def capturing_stream(**kwargs):
        captured_kwargs.append(kwargs)
        async with original_stream(**kwargs) as s:
            yield s

    mock_client.messages.stream = capturing_stream

    with (
        patch("src.llm.client._get_client", return_value=mock_client),
        patch("src.llm.client.build_system_prompt", new_callable=AsyncMock, return_value="system"),
        patch("src.llm.client.registry", mock_registry),
    ):
        result = await generate_response(
            [{"role": "user", "content": "hi"}],
            model="claude-opus-4-6-20250612",
        )

    assert result == "Hello!"
    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["model"] == "claude-opus-4-6-20250612"


async def test_text_not_retracted_for_non_confirmation_tools() -> None:
    """Text in rounds with non-confirmation tools stays in the result."""
    round1 = _make_stream(
        "Let me look that up.",
        [
            _FakeBlock(type="text", text="Let me look that up."),
            _FakeBlock(
                type="tool_use",
                id="tool1",
                name="list_scheduled_tasks",
                input={},
            ),
        ],
    )
    round2 = _make_stream(
        "Here are your tasks.",
        [_FakeBlock(type="text", text="Here are your tasks.")],
    )

    mock_client = _make_mock_client([round1, round2])

    tool_def = ToolDef(
        name="list_scheduled_tasks",
        description="List tasks",
        category="scheduler",
        handler=AsyncMock(return_value=ToolResult(data={"tasks": []})),
        requires_confirmation=False,
    )

    streamed: list[str] = []

    async def on_text_delta(text: str) -> None:
        streamed.append(text)

    mock_registry = MagicMock()
    mock_registry.get_schemas.return_value = [{"name": "list_scheduled_tasks"}]
    mock_registry.get.return_value = tool_def
    mock_registry.execute = AsyncMock(
        return_value=ToolResult(data={"tasks": []})
    )

    with (
        patch("src.llm.client._get_client", return_value=mock_client),
        patch("src.llm.client.build_system_prompt", new_callable=AsyncMock, return_value="system"),
        patch("src.llm.client.registry", mock_registry),
    ):
        result = await generate_response(
            [{"role": "user", "content": "list my tasks"}],
            on_text_delta=on_text_delta,
        )

    # Both rounds streamed and kept in result
    full_streamed = "".join(streamed)
    assert "Let me look that up." in full_streamed
    assert "Here are your tasks." in full_streamed
    assert "Let me look that up." in result
    assert "Here are your tasks." in result


# ---------------------------------------------------------------------------
# Content filter handling
# ---------------------------------------------------------------------------


class _ContentFilterStream:
    """Stream that yields some text then raises a content filter error."""

    def __init__(self, text_before_error: list[str]) -> None:
        self._text_before = text_before_error

    @property
    async def text_stream(self):
        for chunk in self._text_before:
            yield chunk
        raise anthropic.APIStatusError(
            message="Output blocked by content filtering policy",
            response=MagicMock(
                status_code=400,
                headers={},
                json=MagicMock(return_value={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "Output blocked by content filtering policy",
                    },
                }),
            ),
            body={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "Output blocked by content filtering policy",
                },
            },
        )


async def test_content_filter_returns_friendly_message() -> None:
    """Content filter error mid-stream returns a user-friendly message."""
    client = MagicMock()
    stream_obj = _ContentFilterStream(["Partial text"])

    @asynccontextmanager
    async def _stream(**kwargs):
        yield stream_obj

    client.messages.stream = _stream

    mock_registry = MagicMock()
    mock_registry.get_schemas.return_value = []

    streamed: list[str] = []

    async def on_text_delta(text: str) -> None:
        streamed.append(text)

    with (
        patch("src.llm.client._get_client", return_value=client),
        patch("src.llm.client.build_system_prompt", new_callable=AsyncMock, return_value="system"),
        patch("src.llm.client.registry", mock_registry),
    ):
        result = await generate_response(
            [{"role": "user", "content": "tell me something"}],
            on_text_delta=on_text_delta,
        )

    assert "content filter" in result.lower()
    assert "rephras" in result.lower()
    # Partial text is preserved
    assert "Partial text" in result
    # The friendly message was also streamed
    assert any("content filter" in s.lower() for s in streamed)


async def test_content_filter_no_partial_text() -> None:
    """Content filter with no text streamed yet returns just the message."""
    client = MagicMock()
    stream_obj = _ContentFilterStream([])

    @asynccontextmanager
    async def _stream(**kwargs):
        yield stream_obj

    client.messages.stream = _stream

    mock_registry = MagicMock()
    mock_registry.get_schemas.return_value = []

    with (
        patch("src.llm.client._get_client", return_value=client),
        patch("src.llm.client.build_system_prompt", new_callable=AsyncMock, return_value="system"),
        patch("src.llm.client.registry", mock_registry),
    ):
        result = await generate_response(
            [{"role": "user", "content": "something"}],
        )

    assert "content filter" in result.lower()
    assert result.startswith("My response")


async def test_non_content_filter_api_error_reraises() -> None:
    """Non-content-filter APIStatusError still propagates."""
    client = MagicMock()

    class _ErrorStream:
        @property
        async def text_stream(self):
            raise anthropic.APIStatusError(
                message="Rate limit exceeded",
                response=MagicMock(status_code=429, headers={}),
                body={
                    "type": "error",
                    "error": {"type": "rate_limit_error", "message": "Rate limit exceeded"},
                },
            )
            yield  # make it a generator  # noqa: RET503

    @asynccontextmanager
    async def _stream(**kwargs):
        yield _ErrorStream()

    client.messages.stream = _stream

    mock_registry = MagicMock()
    mock_registry.get_schemas.return_value = []

    with (
        patch("src.llm.client._get_client", return_value=client),
        patch("src.llm.client.build_system_prompt", new_callable=AsyncMock, return_value="system"),
        patch("src.llm.client.registry", mock_registry),
    ):
        try:
            await generate_response(
                [{"role": "user", "content": "hi"}],
            )
            raised = False
        except anthropic.APIStatusError:
            raised = True

    assert raised, "Non-content-filter APIStatusError should propagate"
