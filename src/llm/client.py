"""Async Claude API client with streaming and tool-calling loop."""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import anthropic

from src.config import settings
from src.llm.models import ModelManager
from src.llm.prompt import build_system_prompt
from src.tools import registry

logger = logging.getLogger(__name__)

# Safety limit on tool-call round-trips per user message
MAX_TOOL_ROUNDS = 10

_client: anthropic.AsyncAnthropic | None = None


@dataclass
class PendingToolCall:
    """A tool call that requires user confirmation before executing."""

    tool_use_id: str
    tool_name: str
    tool_input: dict[str, Any]
    description: str


def _get_client() -> anthropic.AsyncAnthropic:
    """Lazily initialize the Anthropic client."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def _serialize_content(content: list[Any]) -> list[dict[str, Any]]:
    """Convert SDK content blocks to plain dicts for message history."""
    result: list[dict[str, Any]] = []
    for block in content:
        if block.type == "text":
            result.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            result.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return result


async def generate_response(
    messages: list[dict[str, Any]],
    on_text_delta: Callable[[str], Awaitable[None]] | None = None,
    on_confirm: Callable[[PendingToolCall], Awaitable[bool]] | None = None,
) -> str:
    """Generate a response with full tool-calling loop.

    Streams text to the caller via ``on_text_delta``. When Claude calls
    tools, they are executed automatically and the results fed back.
    Tools marked ``requires_confirmation`` will invoke ``on_confirm``
    first; if the callback returns False (or is not provided), the tool
    call is denied.

    Args:
        messages: Conversation history in Claude API message format.
        on_text_delta: Async callback receiving each text chunk.
        on_confirm: Async callback for tool confirmation; return True to allow.

    Returns:
        The complete assistant text across all rounds.
    """
    client = _get_client()
    tool_schemas = registry.get_schemas()

    # Extract the user's latest text for memory retrieval
    user_msg_text = ""
    if messages:
        last = messages[-1]
        if isinstance(last.get("content"), str):
            user_msg_text = last["content"]

    system_prompt = await build_system_prompt(user_message=user_msg_text)

    loop_messages = list(messages)
    full_text = ""

    for round_num in range(MAX_TOOL_ROUNDS):
        kwargs: dict[str, Any] = {
            "model": ModelManager.get().get_chat_model(),
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": loop_messages,
        }
        if tool_schemas:
            kwargs["tools"] = tool_schemas

        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                full_text += text
                if on_text_delta:
                    await on_text_delta(text)

            response = await stream.get_final_message()

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            return full_text

        logger.info(
            "Round %d: %d tool call(s): %s",
            round_num + 1,
            len(tool_use_blocks),
            ", ".join(b.name for b in tool_use_blocks),
        )

        # Append the assistant turn (with tool_use blocks) to the loop
        loop_messages.append({
            "role": "assistant",
            "content": _serialize_content(response.content),
        })

        # Execute each tool call
        tool_results: list[dict[str, Any]] = []
        for block in tool_use_blocks:
            tool_def = registry.get(block.name)

            # Confirmation gate
            if tool_def and tool_def.requires_confirmation:
                approved = False
                if on_confirm:
                    pending = PendingToolCall(
                        tool_use_id=block.id,
                        tool_name=block.name,
                        tool_input=block.input,
                        description=tool_def.description,
                    )
                    approved = await on_confirm(pending)

                if not approved:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({"error": "User denied this action."}),
                        "is_error": True,
                    })
                    continue

            result = await registry.execute(block.name, block.input)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result.to_content(),
                "is_error": not result.success,
            })

        loop_messages.append({"role": "user", "content": tool_results})

    logger.warning("Hit max tool rounds (%d)", MAX_TOOL_ROUNDS)
    return full_text
