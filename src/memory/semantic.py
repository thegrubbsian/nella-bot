"""Mem0 integration for semantic memory."""

import logging

from mem0 import AsyncMemoryClient

from src.config import settings
from src.memory.models import MemoryEntry

logger = logging.getLogger(__name__)

_client: AsyncMemoryClient | None = None


def _get_client() -> AsyncMemoryClient:
    """Get or create the Mem0 client."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = AsyncMemoryClient(api_key=settings.mem0_api_key)
    return _client


async def remember(content: str, user_id: str = "owner") -> None:
    """Store a memory in Mem0."""
    client = _get_client()
    await client.add(content, user_id=user_id)
    logger.info("Stored memory: %s", content[:80])


async def recall(query: str, user_id: str = "owner", limit: int = 10) -> list[MemoryEntry]:
    """Search memories by semantic similarity."""
    client = _get_client()
    results = await client.search(query, user_id=user_id, limit=limit)
    return [
        MemoryEntry(
            id=r["id"],
            content=r["memory"],
            metadata=r.get("metadata", {}),
        )
        for r in results.get("results", [])
    ]


async def forget(memory_id: str) -> None:
    """Delete a specific memory."""
    client = _get_client()
    await client.delete(memory_id)
    logger.info("Deleted memory: %s", memory_id)
