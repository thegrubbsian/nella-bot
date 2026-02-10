#!/usr/bin/env python3
"""Diagnostic script to test Mem0 connectivity and operations.

Run on the VPS to isolate memory issues from the bot:

    uv run python scripts/test_mem0.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings


def banner(msg: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {msg}")
    print(f"{'=' * 60}")


async def main() -> None:
    banner("Mem0 Diagnostic")

    # 1. Check env
    print(f"\nMEM0_API_KEY set: {bool(settings.mem0_api_key)}")
    if settings.mem0_api_key:
        print(f"MEM0_API_KEY prefix: {settings.mem0_api_key[:8]}...")
    else:
        print("FATAL: MEM0_API_KEY is empty. Set it in .env")
        sys.exit(1)

    mem0_dir = os.environ.get("MEM0_DIR", os.path.expanduser("~/.mem0"))
    print(f"MEM0_DIR: {mem0_dir}")
    print(f"MEM0_DIR exists: {os.path.exists(mem0_dir)}")
    writable = os.access(mem0_dir, os.W_OK) if os.path.exists(mem0_dir) else "N/A (dir missing)"
    print(f"MEM0_DIR writable: {writable}")

    # 2. Try importing mem0
    banner("Step 1: Import mem0")
    try:
        from mem0 import AsyncMemoryClient
        print("OK: mem0 imported successfully")
    except Exception as exc:
        print(f"FAIL: Cannot import mem0: {exc}")
        sys.exit(1)

    # 3. Try creating client
    banner("Step 2: Create AsyncMemoryClient")
    try:
        client = AsyncMemoryClient(api_key=settings.mem0_api_key)
        print(f"OK: Client created: {type(client)}")
    except Exception as exc:
        print(f"FAIL: Cannot create client: {exc}")
        sys.exit(1)

    # 4. Try searching (read operation)
    banner("Step 3: Search (read)")
    try:
        results = await client.search("test query", filters={"user_id": "owner"})
        print(f"OK: Search returned: {type(results)}")
        if isinstance(results, dict):
            print(f"    Keys: {list(results.keys())}")
            print(f"    Results count: {len(results.get('results', []))}")
        elif isinstance(results, list):
            print(f"    Results count: {len(results)}")
        else:
            print(f"    Raw: {results}")
    except Exception as exc:
        print(f"FAIL: Search failed: {type(exc).__name__}: {exc}")
        body = getattr(getattr(exc, "response", None), "text", "")
        if body:
            print(f"    Response body: {body}")

    # 5. Try adding a memory (write operation)
    banner("Step 4: Add memory (write)")
    try:
        result = await client.add(
            "Diagnostic test memory — safe to delete",
            user_id="owner",
            metadata={"source": "diagnostic", "category": "test"},
        )
        print(f"OK: Add returned: {type(result)}")
        print(f"    Result: {result}")
    except Exception as exc:
        print(f"FAIL: Add failed: {type(exc).__name__}: {exc}")
        body = getattr(getattr(exc, "response", None), "text", "")
        if body:
            print(f"    Response body: {body}")

    # 6. Try get_all
    banner("Step 5: Get all memories")
    try:
        all_memories = await client.get_all(filters={"user_id": "owner"})
        if isinstance(all_memories, dict):
            items = all_memories.get("results", [])
        elif isinstance(all_memories, list):
            items = all_memories
        else:
            items = []
        print(f"OK: Total memories for 'owner': {len(items)}")
        for item in items[:3]:
            content = item.get("memory", "?")[:80]
            print(f"    - {content}")
        if len(items) > 3:
            print(f"    ... and {len(items) - 3} more")
    except Exception as exc:
        print(f"FAIL: get_all failed: {type(exc).__name__}: {exc}")
        body = getattr(getattr(exc, "response", None), "text", "")
        if body:
            print(f"    Response body: {body}")

    # 7. Now test via MemoryStore wrapper
    banner("Step 6: Test MemoryStore wrapper")
    try:
        from src.memory.store import MemoryStore
        store = MemoryStore()
        print(f"MemoryStore.enabled: {store.enabled}")
        if store.enabled:
            entries = await store.search("test", limit=3)
            print(f"store.search() returned {len(entries)} entries")
            result = await store.add(
                "MemoryStore wrapper test — safe to delete",
                source="diagnostic",
                category="test",
            )
            print(f"store.add() returned: {result}")
        else:
            print("FAIL: MemoryStore says it's not enabled despite API key being set")
    except Exception as exc:
        print(f"FAIL: MemoryStore error: {type(exc).__name__}: {exc}")

    banner("Done")


if __name__ == "__main__":
    asyncio.run(main())
