"""System prompt assembly with memory retrieval."""

import logging
from pathlib import Path

from src.config import settings
from src.memory.models import MemoryEntry

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _read_config(filename: str) -> str:
    """Read a config markdown file, returning empty string if missing."""
    path = CONFIG_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _format_memories(entries: list[MemoryEntry]) -> str:
    """Format retrieved memories for injection into the system prompt."""
    if not entries:
        return ""

    lines = ["## Recalled Memories\n"]
    for entry in entries:
        lines.append(f"- [{entry.source}/{entry.category}] {entry.content}")
    return "\n".join(lines)


async def _retrieve_memories(user_message: str) -> str:
    """Search the memory store for context relevant to the user's message."""
    try:
        from src.memory.store import MemoryStore

        store = MemoryStore.get()
        if not store.enabled:
            return ""

        entries = await store.search(user_message, limit=10)
        return _format_memories(entries)
    except Exception:
        logger.exception("Memory retrieval failed")
        return ""


async def build_system_prompt(user_message: str = "") -> list[dict]:
    """Assemble the system prompt with optional memory context.

    The static parts (SOUL.md, USER.md) get ``cache_control`` so they're
    cached across tool-calling rounds. Retrieved memories are appended
    as a separate block.

    Args:
        user_message: Current user message for memory retrieval. If empty,
            no memory search is performed.

    Returns:
        List of content blocks for the Claude ``system`` parameter.
    """
    soul = _read_config("SOUL.md")
    user = _read_config("USER.md")

    sections = []
    if soul:
        sections.append(soul)
    if user:
        sections.append(f"# Owner Profile\n\n{user}")

    # Inject Google account list so Claude knows what accounts exist
    accounts = settings.get_google_accounts()
    if accounts:
        default = settings.google_default_account or accounts[0]
        lines = [
            "# Google Accounts\n",
            "When using Google tools, specify which account via the `account` parameter. "
            "If omitted, the default is used.\n",
        ]
        for name in accounts:
            suffix = " (default)" if name == default else ""
            lines.append(f"- {name}{suffix}")
        sections.append("\n".join(lines))

    static_text = "\n\n---\n\n".join(sections)

    # Retrieve relevant memories
    memory_text = ""
    if user_message:
        memory_text = await _retrieve_memories(user_message)

    if memory_text:
        return [
            {
                "type": "text",
                "text": static_text,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": memory_text,
            },
        ]

    return [
        {
            "type": "text",
            "text": static_text,
            "cache_control": {"type": "ephemeral"},
        },
    ]
