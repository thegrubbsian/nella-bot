"""Shared memory store backed by Mem0.

Supports two modes controlled by environment variables:
- Hosted (default): Set MEM0_API_KEY. Uses Mem0's cloud platform.
- Disabled: No MEM0_API_KEY. Memory operations become no-ops and
  search returns empty results. The bot still works, just without
  long-term memory.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from src.config import settings
from src.memory.models import MemoryEntry

logger = logging.getLogger(__name__)


class MemoryStore:
    """Singleton memory store.

    Get the shared instance via ``MemoryStore.get()``.
    """

    _instance: "MemoryStore | None" = None

    def __init__(self) -> None:
        self._client: Any = None
        self._enabled = False
        self._user_id = "owner"
        self._init_backend()

    def _init_backend(self) -> None:
        if settings.mem0_api_key:
            try:
                from mem0 import AsyncMemoryClient

                self._client = AsyncMemoryClient(api_key=settings.mem0_api_key)
                self._enabled = True
                logger.info("Memory store: hosted mode (Mem0 cloud)")
            except Exception:
                logger.exception("Failed to init Mem0 client")
        else:
            logger.warning(
                "Memory store disabled — set MEM0_API_KEY to enable. "
                "Get a free key at https://app.mem0.ai"
            )

    @classmethod
    def get(cls) -> "MemoryStore":
        """Return the shared MemoryStore instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    # -- Write ---------------------------------------------------------------

    async def add(
        self,
        content: str,
        source: str,
        category: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict | None:
        """Store a memory.

        Args:
            content: The text to remember.
            source: "automatic" or "explicit".
            category: One of fact, preference, action_item, workstream,
                      reference, contact, decision, general.
            metadata: Extra key-value pairs to attach.

        Returns:
            The Mem0 result dict, or None if disabled.
        """
        if not self._enabled:
            return None

        full_metadata = {
            "source": source,
            "category": category,
            "created_at": datetime.now(UTC).isoformat(),
            **(metadata or {}),
        }

        try:
            result = await self._client.add(
                content,
                user_id=self._user_id,
                metadata=full_metadata,
            )
            logger.debug("Stored memory [%s/%s]: %s", source, category, content[:80])
            return result
        except Exception:
            logger.exception("Failed to store memory")
            return None

    # -- Read ----------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Search for relevant memories.

        Args:
            query: Natural-language search query.
            limit: Max results to return.

        Returns:
            List of MemoryEntry sorted by relevance.
        """
        if not self._enabled:
            return []

        try:
            raw = await self._client.search(
                query,
                user_id=self._user_id,
                limit=limit,
            )
            return self._normalize(raw)
        except Exception:
            logger.exception("Memory search failed")
            return []

    async def get_all(self) -> list[MemoryEntry]:
        """Retrieve all memories (for debugging/admin)."""
        if not self._enabled:
            return []

        try:
            raw = await self._client.get_all(user_id=self._user_id)
            return self._normalize(raw)
        except Exception:
            logger.exception("Failed to fetch all memories")
            return []

    # -- Delete --------------------------------------------------------------

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID.

        Returns True if successful.
        """
        if not self._enabled:
            return False

        try:
            await self._client.delete(memory_id)
            logger.info("Deleted memory: %s", memory_id)
            return True
        except Exception:
            logger.exception("Failed to delete memory %s", memory_id)
            return False

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _normalize(raw: Any) -> list[MemoryEntry]:
        """Normalize Mem0 results (hosted or local) into MemoryEntry list."""
        if isinstance(raw, dict):
            items = raw.get("results", [])
        elif isinstance(raw, list):
            items = raw
        else:
            items = []

        entries = []
        for item in items:
            meta = item.get("metadata", {}) or {}
            entries.append(
                MemoryEntry(
                    id=item.get("id", ""),
                    content=item.get("memory", ""),
                    source=meta.get("source", "unknown"),
                    category=meta.get("category", "general"),
                    score=item.get("score", 0.0),
                    created_at=meta.get("created_at", ""),
                )
            )
        return entries
