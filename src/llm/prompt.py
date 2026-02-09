"""System prompt assembly from config files with prompt caching."""

from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _read_config(filename: str) -> str:
    """Read a config markdown file, returning empty string if missing."""
    path = CONFIG_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def build_system_prompt() -> list[dict]:
    """Assemble the system prompt as content blocks for the Claude API.

    Combines SOUL.md and USER.md. The final block gets cache_control
    so the prompt is cached across requests.

    Returns:
        List of text content blocks suitable for the `system` parameter.
    """
    soul = _read_config("SOUL.md")
    user = _read_config("USER.md")

    sections = []
    if soul:
        sections.append(soul)
    if user:
        sections.append(f"# Owner Profile\n\n{user}")

    combined = "\n\n---\n\n".join(sections)

    return [
        {
            "type": "text",
            "text": combined,
            "cache_control": {"type": "ephemeral"},
        }
    ]
