"""Async Claude API client with streaming and tool-calling loop."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import anthropic

from src.config import settings
from src.llm.models import ModelManager
from src.llm.prompt import build_system_prompt
from src.tools import registry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.notifications.context import MessageContext

logger = logging.getLogger(__name__)

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


async def complete_text(
    messages: list[dict[str, Any]],
    *,
    system: str | list[dict[str, Any]] | None = None,
    model: str | None = None,
    max_tokens: int = 4096,
) -> str:
    """Single-shot Claude call — no tools, no memory, no streaming.

    Use this for isolated LLM tasks (summarization, extraction, etc.)
    where the full generate_response() pipeline is not needed.
    """
    client = _get_client()
    kwargs: dict[str, Any] = {
        "model": model or ModelManager.get().get_chat_model(),
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system is not None:
        kwargs["system"] = system
    response = await client.messages.create(**kwargs)
    return response.content[0].text


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
    msg_context: MessageContext | None = None,
    model: str | None = None,
) -> str:
    """Generate a response with full tool-calling loop.

    Streams text to the caller via ``on_text_delta``. When Claude calls
    tools, they are executed automatically and the results fed back.
    Tools marked ``requires_confirmation`` will invoke ``on_confirm``
    first; if the callback returns False (or is not provided), the tool
    call is denied.

    Text from rounds that contain confirmation-requiring tools is
    retracted from the return value (since Claude writes it before
    knowing the outcome). The text is still streamed via
    ``on_text_delta`` for real-time display, but the caller's final
    ``edit_text(result)`` replaces it with accurate post-execution text.

    Args:
        messages: Conversation history in Claude API message format.
        on_text_delta: Async callback receiving each text chunk.
        on_confirm: Async callback for tool confirmation; return True to allow.

    Returns:
        The complete assistant text across all rounds (excluding
        retracted confirmation-round text).
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

    max_rounds = settings.max_tool_rounds
    for round_num in range(max_rounds):
        kwargs: dict[str, Any] = {
            "model": model or ModelManager.get().get_chat_model(),
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": loop_messages,
        }
        if tool_schemas:
            kwargs["tools"] = tool_schemas

        # Save length so we can retract text if this round has confirmation tools.
        pre_round_len = len(full_text)

        async with client.messages.stream(**kwargs) as stream:
            first_chunk = True
            async for text in stream.text_stream:
                # Insert a visual separator between streaming rounds so
                # text from successive tool-calling rounds doesn't run
                # together into an unreadable blob.
                if first_chunk and round_num > 0 and full_text and not full_text.endswith("\n"):
                    full_text += "\n\n"
                    if on_text_delta:
                        await on_text_delta("\n\n")
                    first_chunk = False
                full_text += text
                if on_text_delta:
                    await on_text_delta(text)
                first_chunk = False

            response = await stream.get_final_message()

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            return full_text

        # When confirmation is needed, Claude's text was generated before
        # knowing the outcome — it often claims success prematurely.
        # Retract that text from full_text so the final result is accurate.
        # The next round will produce correct text based on actual results.
        # (The text was already streamed to on_text_delta, but the handler's
        # final edit_text(result_text) will replace it with the clean version.)
        has_confirmation = any(
            (td := registry.get(b.name)) and td.requires_confirmation
            for b in tool_use_blocks
        )
        if has_confirmation:
            full_text = full_text[:pre_round_len]

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

            result = await registry.execute(
                block.name, block.input, msg_context=msg_context
            )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result.to_content(),
                "is_error": not result.success,
            })

        loop_messages.append({"role": "user", "content": tool_results})

    logger.warning("Hit max tool rounds (%d)", max_rounds)
    return full_text
