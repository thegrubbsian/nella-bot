"""Automatic ("unconscious") memory extraction.

After each user↔Nella exchange, a background task sends the exchange
to Claude Haiku which decides what (if anything) is worth remembering.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from src.config import settings
from src.memory.store import MemoryStore

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"

_extraction_client: anthropic.AsyncAnthropic | None = None


def _get_extraction_client() -> anthropic.AsyncAnthropic:
    global _extraction_client  # noqa: PLW0603
    if _extraction_client is None:
        _extraction_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _extraction_client


# -- Data structures ---------------------------------------------------------


@dataclass
class ExtractedMemory:
    content: str
    category: str
    importance: str  # high, medium, low


@dataclass
class TopicSwitch:
    previous_topic: str
    decisions_made: str
    open_items: str
    next_steps: str


@dataclass
class ExtractionResult:
    memories: list[ExtractedMemory] = field(default_factory=list)
    topic_switch: TopicSwitch | None = None


# -- Prompt building ---------------------------------------------------------


def _load_rules() -> str:
    path = CONFIG_DIR / "MEMORY_RULES.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "Extract important facts, preferences, action items, and decisions as JSON."


def build_extraction_prompt(
    user_message: str,
    assistant_response: str,
    recent_history: list[dict[str, str]],
) -> str:
    """Build the user-message content sent to the extraction model."""
    history_text = ""
    if recent_history:
        lines = []
        for msg in recent_history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str):
                lines.append(f"<{role}>{content}</{role}>")
        history_text = f"<recent_history>\n{''.join(lines)}\n</recent_history>\n\n"

    return (
        f"{history_text}"
        f"<exchange>\n"
        f"<user>{user_message}</user>\n"
        f"<assistant>{assistant_response}</assistant>\n"
        f"</exchange>\n\n"
        f"Analyze this exchange. Return JSON only."
    )


# -- Parsing -----------------------------------------------------------------


def parse_extraction_result(text: str) -> ExtractionResult:
    """Parse the extraction model's JSON output."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown fences
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    data = json.loads(text[start:end])
                except json.JSONDecodeError:
                    logger.warning("Failed to parse extraction JSON")
                    return ExtractionResult()
            else:
                return ExtractionResult()
        else:
            logger.warning("Failed to parse extraction JSON")
            return ExtractionResult()

    memories = [
        ExtractedMemory(
            content=m.get("content", ""),
            category=m.get("category", "general"),
            importance=m.get("importance", "low"),
        )
        for m in data.get("memories", [])
        if m.get("content")
    ]

    topic_switch = None
    ts = data.get("topic_switch")
    if ts and isinstance(ts, dict):
        topic_switch = TopicSwitch(
            previous_topic=ts.get("previous_topic", ""),
            decisions_made=ts.get("decisions_made", ""),
            open_items=ts.get("open_items", ""),
            next_steps=ts.get("next_steps", ""),
        )

    return ExtractionResult(memories=memories, topic_switch=topic_switch)


# -- Main pipeline -----------------------------------------------------------


async def extract_and_save(
    user_message: str,
    assistant_response: str,
    recent_history: list[dict[str, str]],
    conversation_id: str,
) -> None:
    """Background task: extract memories from an exchange and save them.

    Call via ``asyncio.create_task(extract_and_save(...))``.
    """
    if not settings.memory_extraction_enabled:
        return

    store = MemoryStore.get()
    if not store.enabled:
        return

    try:
        client = _get_extraction_client()
        rules = _load_rules()
        prompt = build_extraction_prompt(user_message, assistant_response, recent_history)

        response = await client.messages.create(
            model=settings.memory_extraction_model,
            max_tokens=1024,
            system=rules,
            messages=[{"role": "user", "content": prompt}],
        )

        result = parse_extraction_result(response.content[0].text)

        # Save medium and high importance memories
        saved = 0
        for mem in result.memories:
            if mem.importance in ("medium", "high"):
                await store.add(
                    content=mem.content,
                    source="automatic",
                    category=mem.category,
                    metadata={
                        "importance": mem.importance,
                        "conversation_id": conversation_id,
                    },
                )
                saved += 1

        # Save workstream snapshot on topic switch
        if result.topic_switch:
            ts = result.topic_switch
            snapshot = (
                f"Topic: {ts.previous_topic}\n"
                f"Decisions: {ts.decisions_made}\n"
                f"Open: {ts.open_items}\n"
                f"Next: {ts.next_steps}"
            )
            await store.add(
                content=snapshot,
                source="automatic",
                category="workstream",
                metadata={"conversation_id": conversation_id},
            )
            saved += 1

        if saved:
            logger.info("Extracted %d memories from exchange", saved)

    except Exception:
        logger.exception("Memory extraction failed (non-fatal)")
