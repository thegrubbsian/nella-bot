"""Tests for automatic memory extraction."""

import json
from unittest.mock import AsyncMock, patch

from src.memory.automatic import (
    ExtractionResult,
    build_extraction_prompt,
    extract_and_save,
    parse_extraction_result,
)

# -- build_extraction_prompt -------------------------------------------------


def test_prompt_includes_exchange() -> None:
    prompt = build_extraction_prompt(
        user_message="I love coffee",
        assistant_response="Good to know!",
        recent_history=[],
    )
    assert "I love coffee" in prompt
    assert "Good to know!" in prompt
    assert "<user>" in prompt
    assert "<assistant>" in prompt


def test_prompt_includes_recent_history() -> None:
    history = [
        {"role": "user", "content": "Earlier message"},
        {"role": "assistant", "content": "Earlier reply"},
    ]
    prompt = build_extraction_prompt("new msg", "new reply", history)
    assert "Earlier message" in prompt
    assert "<recent_history>" in prompt


def test_prompt_empty_history() -> None:
    prompt = build_extraction_prompt("hello", "hi", [])
    assert "<recent_history>" not in prompt


# -- parse_extraction_result -------------------------------------------------


def test_parse_valid_json() -> None:
    raw = json.dumps(
        {
            "memories": [
                {"content": "Likes coffee", "category": "preference", "importance": "medium"},
                {"content": "Lives in NYC", "category": "fact", "importance": "high"},
            ],
            "topic_switch": None,
        }
    )
    result = parse_extraction_result(raw)
    assert len(result.memories) == 2
    assert result.memories[0].content == "Likes coffee"
    assert result.memories[1].importance == "high"
    assert result.topic_switch is None


def test_parse_with_topic_switch() -> None:
    raw = json.dumps(
        {
            "memories": [],
            "topic_switch": {
                "previous_topic": "Budget planning",
                "decisions_made": "Cap at $50k",
                "open_items": "Need vendor quotes",
                "next_steps": "Email vendors",
            },
        }
    )
    result = parse_extraction_result(raw)
    assert result.topic_switch is not None
    assert result.topic_switch.previous_topic == "Budget planning"
    assert result.topic_switch.next_steps == "Email vendors"


def test_parse_empty_memories() -> None:
    raw = json.dumps({"memories": [], "topic_switch": None})
    result = parse_extraction_result(raw)
    assert len(result.memories) == 0


def test_parse_invalid_json_returns_empty() -> None:
    result = parse_extraction_result("not valid json at all")
    assert isinstance(result, ExtractionResult)
    assert len(result.memories) == 0


def test_parse_json_in_markdown_fences() -> None:
    payload = {
        "memories": [{"content": "test", "category": "fact", "importance": "high"}],
        "topic_switch": None,
    }
    inner = json.dumps(payload)
    raw = f"```json\n{inner}\n```"
    result = parse_extraction_result(raw)
    assert len(result.memories) == 1


def test_parse_skips_empty_content() -> None:
    raw = json.dumps(
        {
            "memories": [
                {"content": "", "category": "fact", "importance": "high"},
                {"content": "Real memory", "category": "fact", "importance": "high"},
            ],
            "topic_switch": None,
        }
    )
    result = parse_extraction_result(raw)
    assert len(result.memories) == 1


# -- extract_and_save --------------------------------------------------------


async def test_extract_saves_medium_and_high_only() -> None:
    mock_store = AsyncMock()
    mock_store.enabled = True

    response_json = json.dumps(
        {
            "memories": [
                {"content": "Important fact", "category": "fact", "importance": "high"},
                {"content": "Useful detail", "category": "preference", "importance": "medium"},
                {"content": "Trivial thing", "category": "general", "importance": "low"},
            ],
            "topic_switch": None,
        }
    )

    with (
        patch("src.memory.automatic.MemoryStore.get", return_value=mock_store),
        patch("src.llm.client.complete_text", new_callable=AsyncMock, return_value=response_json),
        patch("src.memory.automatic.settings") as mock_settings,
    ):
        mock_settings.memory_extraction_enabled = True

        await extract_and_save("hello", "hi", [], "conv_1")

    # Only high and medium should be saved (2 of 3)
    assert mock_store.add.call_count == 2


async def test_extract_saves_topic_switch() -> None:
    mock_store = AsyncMock()
    mock_store.enabled = True

    response_json = json.dumps(
        {
            "memories": [],
            "topic_switch": {
                "previous_topic": "Budget",
                "decisions_made": "Cap at $50k",
                "open_items": "Vendor quotes",
                "next_steps": "Email vendors",
            },
        }
    )

    with (
        patch("src.memory.automatic.MemoryStore.get", return_value=mock_store),
        patch("src.llm.client.complete_text", new_callable=AsyncMock, return_value=response_json),
        patch("src.memory.automatic.settings") as mock_settings,
    ):
        mock_settings.memory_extraction_enabled = True

        await extract_and_save("let's switch topics", "sure", [], "conv_1")

    assert mock_store.add.call_count == 1
    call_kwargs = mock_store.add.call_args[1]
    assert call_kwargs["category"] == "workstream"
    assert "Budget" in call_kwargs["content"]


async def test_extract_disabled_is_noop() -> None:
    with patch("src.memory.automatic.settings") as mock_settings:
        mock_settings.memory_extraction_enabled = False
        # Should return without doing anything
        await extract_and_save("hello", "hi", [], "conv_1")
