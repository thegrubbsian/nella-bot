"""Smart message chunking for Telegram's 4,096-character limit."""

from __future__ import annotations

import re

# 96-char buffer below Telegram's 4,096 hard limit (room for Markdown overhead)
DEFAULT_MAX_LENGTH = 4000


def split_message(text: str, max_length: int = DEFAULT_MAX_LENGTH) -> list[str]:
    """Split *text* into chunks that each fit within *max_length* characters.

    Split priority (best → worst boundary):
      1. Double newlines (paragraph breaks)
      2. Markdown headers (``\\n# ``, ``\\n## ``, etc.)
      3. Single newlines
      4. Sentence endings (``. ``, ``! ``, ``? ``)
      5. Word boundaries (spaces)
      6. Hard cut (last resort)
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        split_pos = _find_split_point(remaining, max_length)
        chunks.append(remaining[:split_pos].rstrip())
        remaining = remaining[split_pos:].lstrip("\n")

    return chunks or [""]


def _find_split_point(text: str, max_length: int) -> int:
    """Find the best position to split *text* within *max_length* characters."""
    window = text[:max_length]

    # 1. Double newline (paragraph break) — split *after* the break
    pos = window.rfind("\n\n")
    if pos > 0:
        return pos + 2

    # 2. Markdown header on its own line (e.g. "\n# ", "\n## ")
    match = None
    for m in re.finditer(r"\n#{1,6} ", window):
        match = m
    if match and match.start() > 0:
        return match.start() + 1  # keep the \n with the previous chunk? No — start new chunk at #

    # 3. Single newline
    pos = window.rfind("\n")
    if pos > 0:
        return pos + 1

    # 4. Sentence ending (". ", "! ", "? ")
    for punct in (". ", "! ", "? "):
        pos = window.rfind(punct)
        if pos > 0:
            return pos + len(punct)

    # 5. Word boundary (space)
    pos = window.rfind(" ")
    if pos > 0:
        return pos + 1

    # 6. Hard cut
    return max_length
