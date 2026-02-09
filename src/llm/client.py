"""Async Claude API client with streaming."""

import logging
from collections.abc import AsyncGenerator

import anthropic

from src.config import settings
from src.llm.prompt import build_system_prompt

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    """Lazily initialize the Anthropic client."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def stream_response(
    messages: list[dict[str, str]],
) -> AsyncGenerator[str, None]:
    """Stream a response from Claude, yielding text chunks.

    Args:
        messages: Conversation history in Claude API format.

    Yields:
        Text delta strings as they arrive.
    """
    client = _get_client()
    system_prompt = build_system_prompt()

    async with client.messages.stream(
        model=settings.claude_model,
        max_tokens=4096,
        system=system_prompt,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text
