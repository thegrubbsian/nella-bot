"""Data models for memory and conversation storage."""

from pydantic import BaseModel


class Message(BaseModel):
    """A single conversation message."""

    role: str
    content: str
    created_at: str


class MemoryEntry(BaseModel):
    """A memory retrieved from the store."""

    id: str
    content: str
    source: str = "unknown"  # "automatic" or "explicit"
    category: str = "general"
    score: float = 0.0
    created_at: str = ""
