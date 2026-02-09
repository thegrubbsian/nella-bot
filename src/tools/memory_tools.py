"""Explicit ("conscious") memory tools.

These are tools Claude can call when the user explicitly asks to
remember, forget, or recall something.
"""

from pydantic import Field

from src.memory.store import MemoryStore
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

# -- remember_this -----------------------------------------------------------


class RememberParams(ToolParams):
    content: str = Field(description="The information to remember")
    category: str = Field(
        default="general",
        description=(
            "Category: fact, preference, action_item, reference, "
            "contact, decision, or general"
        ),
    )


@registry.tool(
    name="remember_this",
    description=(
        "Store something in long-term memory. Use when the user says "
        "'remember X', 'save this', 'don't forget', etc."
    ),
    category="memory",
    params_model=RememberParams,
)
async def remember_this(content: str, category: str = "general") -> ToolResult:
    store = MemoryStore.get()
    result = await store.add(content=content, source="explicit", category=category)
    if result is None and not store.enabled:
        return ToolResult(error="Memory store is not configured.")
    return ToolResult(data={"remembered": True, "content": content, "category": category})


# -- forget_this -------------------------------------------------------------


class ForgetParams(ToolParams):
    query: str = Field(description="What to forget — search query to find matching memories")


@registry.tool(
    name="forget_this",
    description=(
        "Forget something from memory. Searches for matching memories and "
        "deletes them. Use when the user says 'forget about X' or "
        "'delete that memory'. Always tell the user what you found and "
        "confirm before calling this tool."
    ),
    category="memory",
    params_model=ForgetParams,
)
async def forget_this(query: str) -> ToolResult:
    store = MemoryStore.get()
    matches = await store.search(query, limit=5)
    if not matches:
        return ToolResult(data={"deleted": 0, "message": "No matching memories found."})

    deleted = 0
    deleted_items = []
    for entry in matches:
        success = await store.delete(entry.id)
        if success:
            deleted += 1
            deleted_items.append(entry.content)

    return ToolResult(data={
        "deleted": deleted,
        "items": deleted_items,
    })


# -- recall ------------------------------------------------------------------


class RecallParams(ToolParams):
    query: str = Field(description="What to search for in memory")
    limit: int = Field(default=5, description="Maximum number of results")


@registry.tool(
    name="recall",
    description=(
        "Search long-term memory. Use when the user asks 'what do you "
        "remember about X', 'do you know my Y', or when you need to "
        "check if you have relevant context."
    ),
    category="memory",
    params_model=RecallParams,
)
async def recall(query: str, limit: int = 5) -> ToolResult:
    store = MemoryStore.get()
    entries = await store.search(query, limit=limit)
    if not entries:
        return ToolResult(data={"results": [], "count": 0})

    results = [
        {
            "content": e.content,
            "source": e.source,
            "category": e.category,
        }
        for e in entries
    ]
    return ToolResult(data={"results": results, "count": len(results)})


# -- save_reference ----------------------------------------------------------


class SaveReferenceParams(ToolParams):
    url: str = Field(description="URL of the article or resource")
    title: str = Field(description="Title of the article or resource")
    summary: str = Field(description="Brief summary of the content")


@registry.tool(
    name="save_reference",
    description=(
        "Save a link or article reference with a summary. Use when the "
        "user shares a URL and says 'save this', 'remember this article', "
        "or 'I'll want to talk about this later'."
    ),
    category="memory",
    params_model=SaveReferenceParams,
)
async def save_reference(url: str, title: str, summary: str) -> ToolResult:
    store = MemoryStore.get()
    content = f"{title}\nURL: {url}\nSummary: {summary}"
    result = await store.add(
        content=content,
        source="explicit",
        category="reference",
        metadata={"url": url, "title": title},
    )
    if result is None and not store.enabled:
        return ToolResult(error="Memory store is not configured.")
    return ToolResult(data={"saved": True, "title": title, "url": url})
