"""Data models for memory and conversation storage."""

from pydantic import BaseModel


class Message(BaseModel):
    """A single conversation message."""

    role: str
    content: str
    created_at: str


class MemoryEntry(BaseModel):
    """A stored memory from Mem0."""

    id: str
    content: str
    metadata: dict[str, str] = {}
