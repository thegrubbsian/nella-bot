"""System prompt assembly from config files."""

from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _read_config(filename: str) -> str:
    """Read a config markdown file, returning empty string if missing."""
    path = CONFIG_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


async def build_system_prompt() -> str:
    """Assemble the full system prompt from config files.

    Combines SOUL.md (personality), USER.md (owner profile),
    TOOLS.md (available tools), and MEMORY.md (persistent notes).
    """
    soul = _read_config("SOUL.md")
    user = _read_config("USER.md")
    tools = _read_config("TOOLS.md")
    memory = _read_config("MEMORY.md")

    sections = []

    if soul:
        sections.append(soul)
    if user:
        sections.append(f"# Owner Profile\n\n{user}")
    if memory:
        sections.append(f"# Persistent Memory\n\n{memory}")
    if tools:
        sections.append(f"# Available Tools\n\n{tools}")

    return "\n\n---\n\n".join(sections)
