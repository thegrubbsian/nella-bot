"""System prompt assembly with memory retrieval."""

import logging
from datetime import datetime
from pathlib import Path

try:
    import zoneinfo
except ImportError:  # pragma: no cover
    from backports import zoneinfo  # type: ignore[no-redef]

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

    The static parts (SOUL.md, USER.md, TOOLS.md) get ``cache_control``
    so they're cached across tool-calling rounds. Retrieved memories are
    appended as a separate block.

    Args:
        user_message: Current user message for memory retrieval. If empty,
            no memory search is performed.

    Returns:
        List of content blocks for the Claude ``system`` parameter.
    """
    soul = _read_config("SOUL.md")
    user = _read_config("USER.md")
    tools = _read_config("TOOLS.md")

    sections = []
    if soul:
        sections.append(soul)
    if user:
        sections.append(f"# Owner Profile\n\n{user}")
    if tools:
        sections.append(tools)

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

    # Inject Nella's source repo so she can reference her own code
    if settings.nella_source_repo:
        sections.append(
            "# Source Code\n\n"
            f"Your own source code is at GitHub repo `{settings.nella_source_repo}`. "
            "When debugging yourself or exploring your own code, use GitHub tools "
            "with this repo. Combine with `query_logs` for full self-debugging."
        )

    # Inject LinkedIn availability
    from src.integrations.linkedin_auth import LinkedInAuth

    if LinkedInAuth.enabled():
        sections.append(
            "# LinkedIn\n\n"
            "LinkedIn is connected. You can create posts with `linkedin_create_post` "
            "and comment on posts with `linkedin_post_comment` (provide the post URL). "
            "Both require confirmation before executing."
        )

    # Inject Notion config when API key is set
    if settings.notion_api_key:
        notion_config = _read_config("NOTION.md")
        if notion_config:
            sections.append(notion_config)
        else:
            sections.append(
                "# Notion\n\n"
                "Notion is connected. You can search, query databases, create/update pages, "
                "read content, and archive pages. Use notion_list_databases to discover "
                "available databases."
            )

    static_text = "\n\n---\n\n".join(sections)

    # Current time — injected on every call (not cached)
    tz = zoneinfo.ZoneInfo(settings.scheduler_timezone)
    now = datetime.now(tz)
    time_text = (
        f"Current time: {now.strftime('%A, %B %d, %Y %I:%M %p %Z')} "
        f"({settings.scheduler_timezone})"
    )

    # Retrieve relevant memories
    memory_text = ""
    if user_message:
        memory_text = await _retrieve_memories(user_message)

    blocks: list[dict] = [
        {
            "type": "text",
            "text": static_text,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": time_text,
        },
    ]

    if memory_text:
        blocks.append({"type": "text", "text": memory_text})

    return blocks
