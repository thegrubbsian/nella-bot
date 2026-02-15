"""Notion tools — generic database and page CRUD."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import Field

from src.config import settings
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

if TYPE_CHECKING:
    from notion_client import AsyncClient

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 50_000
RICH_TEXT_CHAR_LIMIT = 2000
DEFAULT_PAGE_SIZE = 25

_client: AsyncClient | None = None


def _get_client() -> AsyncClient:
    """Return a lazily-initialised Notion AsyncClient singleton."""
    global _client  # noqa: PLW0603
    if _client is None:
        if not settings.notion_api_key:
            msg = "NOTION_API_KEY is not configured."
            raise ValueError(msg)
        from notion_client import AsyncClient

        # Pin to 2022-06-28 — the stable, well-documented API version.
        # SDK v2.7.0 defaults to 2025-09-03 which restructured databases
        # around "data sources" and changed property value formats.
        _client = AsyncClient(
            auth=settings.notion_api_key,
            notion_version="2022-06-28",
        )
    return _client


# ---------------------------------------------------------------------------
# Rich text / block helpers
# ---------------------------------------------------------------------------


def _rich_text_to_plain(rich_text: list[dict[str, Any]]) -> str:
    """Join Notion rich text array into a plain string."""
    return "".join(item.get("plain_text", "") for item in rich_text)


def _plain_to_rich_text(text: str) -> list[dict[str, Any]]:
    """Wrap a plain string into Notion rich text format.

    Notion limits each rich text element to 2000 characters, so long
    strings are split into multiple elements.
    """
    if not text:
        return []
    chunks = [text[i : i + RICH_TEXT_CHAR_LIMIT] for i in range(0, len(text), RICH_TEXT_CHAR_LIMIT)]
    return [{"type": "text", "text": {"content": chunk}} for chunk in chunks]


def _text_to_blocks(text: str) -> list[dict[str, Any]]:
    """Convert plain text to Notion paragraph blocks.

    Splits on double newlines into separate paragraphs. Each paragraph's
    rich text respects the 2000-character limit.
    """
    if not text:
        return []
    paragraphs = text.split("\n\n")
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _plain_to_rich_text(para)},
        }
        for para in paragraphs
        if para.strip()
    ]


def _extract_block_text(block: dict[str, Any]) -> str:
    """Extract plain text from a single Notion block."""
    block_type = block.get("type", "")
    type_data = block.get(block_type, {})
    rich_text = type_data.get("rich_text", [])
    if rich_text:
        return _rich_text_to_plain(rich_text)
    # Some block types (e.g. child_page, child_database) don't have rich_text
    if "title" in type_data:
        return type_data["title"]
    return ""


# ---------------------------------------------------------------------------
# Property formatting helpers
# ---------------------------------------------------------------------------


def _format_property_value(prop: dict[str, Any]) -> Any:
    """Convert a single Notion property to a simple Python value."""
    ptype = prop.get("type", "")

    if ptype == "title":
        return _rich_text_to_plain(prop.get("title", []))
    if ptype == "rich_text":
        return _rich_text_to_plain(prop.get("rich_text", []))
    if ptype == "number":
        return prop.get("number")
    if ptype == "select":
        sel = prop.get("select")
        return sel["name"] if sel else None
    if ptype == "multi_select":
        return [item["name"] for item in prop.get("multi_select", [])]
    if ptype == "status":
        status = prop.get("status")
        return status["name"] if status else None
    if ptype == "date":
        date = prop.get("date")
        if not date:
            return None
        result: dict[str, Any] = {"start": date.get("start")}
        if date.get("end"):
            result["end"] = date["end"]
        return result
    if ptype == "checkbox":
        return prop.get("checkbox")
    if ptype == "url":
        return prop.get("url")
    if ptype == "email":
        return prop.get("email")
    if ptype == "phone_number":
        return prop.get("phone_number")
    if ptype == "formula":
        formula = prop.get("formula", {})
        ftype = formula.get("type", "")
        return formula.get(ftype)
    if ptype == "relation":
        return [item["id"] for item in prop.get("relation", [])]
    if ptype == "people":
        return [
            person.get("name", person.get("id", ""))
            for person in prop.get("people", [])
        ]
    if ptype == "files":
        files = prop.get("files", [])
        return [
            f.get("name", f.get("external", {}).get("url", ""))
            for f in files
        ]
    if ptype == "unique_id":
        uid = prop.get("unique_id", {})
        prefix = uid.get("prefix", "")
        number = uid.get("number", "")
        return f"{prefix}-{number}" if prefix else str(number)
    if ptype == "created_time":
        return prop.get("created_time")
    if ptype == "last_edited_time":
        return prop.get("last_edited_time")
    if ptype == "created_by":
        person = prop.get("created_by", {})
        return person.get("name", person.get("id", ""))
    if ptype == "last_edited_by":
        person = prop.get("last_edited_by", {})
        return person.get("name", person.get("id", ""))
    if ptype == "rollup":
        rollup = prop.get("rollup", {})
        rtype = rollup.get("type", "")
        return rollup.get(rtype)

    return str(prop)


def _format_page_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Format all properties of a Notion page into simple values."""
    return {name: _format_property_value(prop) for name, prop in properties.items()}


def _format_page_summary(page: dict[str, Any]) -> dict[str, Any]:
    """Build a concise summary dict from a Notion page object."""
    return {
        "id": page["id"],
        "url": page.get("url", ""),
        "archived": page.get("archived", False),
        "created_time": page.get("created_time", ""),
        "last_edited_time": page.get("last_edited_time", ""),
        "properties": _format_page_properties(page.get("properties", {})),
    }


async def _build_properties_payload(
    properties: dict[str, Any],
    database_id: str | None = None,
) -> dict[str, Any]:
    """Convert simple {name: value} properties to Notion API format.

    When ``database_id`` is provided, the database schema is fetched to
    determine property types for correct formatting. Without it, values
    are sent as-is (caller must provide Notion-formatted values).
    """
    if database_id is None:
        return properties

    client = _get_client()
    db = await client.databases.retrieve(database_id=database_id)
    schema = db.get("properties", {})

    payload: dict[str, Any] = {}
    for name, value in properties.items():
        prop_schema = schema.get(name)
        if prop_schema is None:
            # Property not in schema — pass through as-is
            payload[name] = value
            continue

        ptype = prop_schema.get("type", "")
        payload[name] = _format_value_for_type(ptype, value)

    return payload


def _format_value_for_type(ptype: str, value: Any) -> dict[str, Any]:
    """Format a simple value into Notion property format based on type."""
    if ptype == "title":
        text = str(value) if value is not None else ""
        return {"title": _plain_to_rich_text(text)}
    if ptype == "rich_text":
        text = str(value) if value is not None else ""
        return {"rich_text": _plain_to_rich_text(text)}
    if ptype == "number":
        return {"number": value}
    if ptype == "select":
        if value is None:
            return {"select": None}
        return {"select": {"name": str(value)}}
    if ptype == "multi_select":
        if isinstance(value, list):
            return {"multi_select": [{"name": str(v)} for v in value]}
        return {"multi_select": [{"name": str(value)}]}
    if ptype == "status":
        if value is None:
            return {"status": None}
        return {"status": {"name": str(value)}}
    if ptype == "date":
        if value is None:
            return {"date": None}
        if isinstance(value, dict):
            return {"date": value}
        return {"date": {"start": str(value)}}
    if ptype == "checkbox":
        return {"checkbox": bool(value)}
    if ptype == "url":
        return {"url": str(value) if value is not None else None}
    if ptype == "email":
        return {"email": str(value) if value is not None else None}
    if ptype == "phone_number":
        return {"phone_number": str(value) if value is not None else None}
    if ptype == "relation":
        if isinstance(value, list):
            return {"relation": [{"id": str(v)} for v in value]}
        return {"relation": [{"id": str(value)}]}
    if ptype == "people":
        if isinstance(value, list):
            return {"people": [{"id": str(v)} for v in value]}
        return {"people": [{"id": str(value)}]}

    # For types that can't be set via API (formula, rollup, etc.),
    # or unknown types, pass through as-is
    return {ptype: value}


def _notion_error_message(exc: Exception) -> str:
    """Extract a human-readable error message from a Notion API error."""
    # notion_client.errors.APIResponseError has code, status, message
    if hasattr(exc, "message"):
        return str(exc.message)
    return str(exc)


# ---------------------------------------------------------------------------
# Param models
# ---------------------------------------------------------------------------


class NotionSearchParams(ToolParams):
    query: str = Field(description="Search query (matches page and database titles)")
    filter_type: str | None = Field(
        default=None,
        description="Filter results by type: 'page' or 'database'. Returns both if omitted.",
    )
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE,
        description="Maximum results to return (1-100)",
        ge=1,
        le=100,
    )


class NotionListDatabasesParams(ToolParams):
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE,
        description="Maximum databases to return (1-100)",
        ge=1,
        le=100,
    )


class NotionGetDatabaseParams(ToolParams):
    database_id: str = Field(description="The ID of the database to retrieve")


class NotionQueryDatabaseParams(ToolParams):
    database_id: str = Field(description="The ID of the database to query")
    filter: dict[str, Any] | None = Field(
        default=None,
        description="Notion filter object (see Notion API docs for filter syntax)",
    )
    sorts: list[dict[str, Any]] | None = Field(
        default=None,
        description="Sort criteria, e.g. [{'property': 'Due Date', 'direction': 'ascending'}]",
    )
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE,
        description="Maximum pages to return (1-100)",
        ge=1,
        le=100,
    )
    start_cursor: str | None = Field(
        default=None,
        description="Pagination cursor from a previous query's next_cursor",
    )


class NotionGetPageParams(ToolParams):
    page_id: str = Field(description="The ID of the page to retrieve")


class NotionReadPageContentParams(ToolParams):
    page_id: str = Field(description="The ID of the page whose content to read")


class NotionCreatePageParams(ToolParams):
    database_id: str = Field(description="The database to create the page in")
    properties: dict[str, Any] = Field(
        description=(
            "Page properties as {name: value}. Values are auto-formatted based on "
            "the database schema (e.g. {'Name': 'My Task', 'Status': 'Not Started'})."
        ),
    )
    content: str | None = Field(
        default=None,
        description=(
            "Optional page body text (plain text, split into paragraphs on double newlines)"
        ),
    )


class NotionUpdatePageParams(ToolParams):
    page_id: str = Field(description="The ID of the page to update")
    properties: dict[str, Any] = Field(
        description=(
            "Properties to update as {name: value}. Only include properties you want to change."
        ),
    )


class NotionArchivePageParams(ToolParams):
    page_id: str = Field(description="The ID of the page to archive (soft-delete)")


class NotionAppendContentParams(ToolParams):
    page_id: str = Field(description="The ID of the page to append content to")
    content: str = Field(
        description="Text to append (plain text, split into paragraphs on double newlines)",
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@registry.tool(
    name="notion_search",
    description=(
        "Search Notion by title. Finds pages and databases whose titles match "
        "the query. Note: this only searches titles, not page body content. "
        "For content-based filtering, use notion_query_database with a filter."
    ),
    category="notion",
    params_model=NotionSearchParams,
)
async def notion_search(
    query: str,
    filter_type: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> ToolResult:
    try:
        client = _get_client()
        kwargs: dict[str, Any] = {"query": query, "page_size": page_size}
        if filter_type in ("page", "database"):
            kwargs["filter"] = {"value": filter_type, "property": "object"}
        response = await client.search(**kwargs)
        results = [_format_page_summary(item) for item in response.get("results", [])]
        return ToolResult(data={
            "results": results,
            "count": len(results),
            "has_more": response.get("has_more", False),
        })
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


@registry.tool(
    name="notion_list_databases",
    description=(
        "List all databases shared with the Notion integration. Use this to "
        "discover available databases and their IDs."
    ),
    category="notion",
    params_model=NotionListDatabasesParams,
)
async def notion_list_databases(
    page_size: int = DEFAULT_PAGE_SIZE,
) -> ToolResult:
    try:
        client = _get_client()
        response = await client.search(
            filter={"value": "database", "property": "object"},
            page_size=page_size,
        )
        databases = []
        for db in response.get("results", []):
            title_parts = db.get("title", [])
            title = _rich_text_to_plain(title_parts)
            # Format property schema for discovery
            props = {}
            for name, prop in db.get("properties", {}).items():
                prop_info: dict[str, Any] = {"type": prop.get("type", "")}
                # Include select/status options for discoverability
                ptype = prop.get("type", "")
                if ptype == "select" and prop.get("select", {}).get("options"):
                    prop_info["options"] = [
                        opt["name"] for opt in prop["select"]["options"]
                    ]
                elif ptype == "multi_select" and prop.get("multi_select", {}).get("options"):
                    prop_info["options"] = [
                        opt["name"] for opt in prop["multi_select"]["options"]
                    ]
                elif ptype == "status" and prop.get("status", {}).get("options"):
                    prop_info["options"] = [
                        opt["name"] for opt in prop["status"]["options"]
                    ]
                props[name] = prop_info
            databases.append({
                "id": db["id"],
                "title": title,
                "url": db.get("url", ""),
                "properties": props,
            })
        return ToolResult(data={
            "databases": databases,
            "count": len(databases),
            "has_more": response.get("has_more", False),
        })
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


@registry.tool(
    name="notion_get_database",
    description=(
        "Get a database's schema — property names, types, and select/status options. "
        "Use this to understand a database's structure before querying or creating pages."
    ),
    category="notion",
    params_model=NotionGetDatabaseParams,
)
async def notion_get_database(database_id: str) -> ToolResult:
    try:
        client = _get_client()
        db = await client.databases.retrieve(database_id=database_id)
        title_parts = db.get("title", [])
        title = _rich_text_to_plain(title_parts)
        props = {}
        for name, prop in db.get("properties", {}).items():
            prop_info: dict[str, Any] = {"type": prop.get("type", "")}
            ptype = prop.get("type", "")
            if ptype == "select" and prop.get("select", {}).get("options"):
                prop_info["options"] = [
                    opt["name"] for opt in prop["select"]["options"]
                ]
            elif ptype == "multi_select" and prop.get("multi_select", {}).get("options"):
                prop_info["options"] = [
                    opt["name"] for opt in prop["multi_select"]["options"]
                ]
            elif ptype == "status" and prop.get("status", {}).get("options"):
                prop_info["options"] = [
                    opt["name"] for opt in prop["status"]["options"]
                ]
            props[name] = prop_info
        return ToolResult(data={
            "id": db["id"],
            "title": title,
            "url": db.get("url", ""),
            "properties": props,
        })
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


@registry.tool(
    name="notion_query_database",
    description=(
        "Query a Notion database with optional filters and sorts. Returns pages "
        "matching the criteria. Supports pagination via start_cursor."
    ),
    category="notion",
    params_model=NotionQueryDatabaseParams,
)
async def notion_query_database(
    database_id: str,
    filter: dict[str, Any] | None = None,  # noqa: A002
    sorts: list[dict[str, Any]] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    start_cursor: str | None = None,
) -> ToolResult:
    try:
        client = _get_client()
        # SDK v2.7.0 removed databases.query() (moved to data_sources).
        # Call the endpoint directly via client.request().
        body: dict[str, Any] = {"page_size": page_size}
        if filter is not None:
            body["filter"] = filter
        if sorts is not None:
            body["sorts"] = sorts
        if start_cursor is not None:
            body["start_cursor"] = start_cursor
        response = await client.request(
            path=f"databases/{database_id}/query",
            method="POST",
            body=body,
        )
        pages = [_format_page_summary(page) for page in response.get("results", [])]
        return ToolResult(data={
            "pages": pages,
            "count": len(pages),
            "has_more": response.get("has_more", False),
            "next_cursor": response.get("next_cursor"),
        })
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


@registry.tool(
    name="notion_get_page",
    description=(
        "Get a Notion page's properties (not its body content "
        "— use notion_read_page_content for that)."
    ),
    category="notion",
    params_model=NotionGetPageParams,
)
async def notion_get_page(page_id: str) -> ToolResult:
    try:
        client = _get_client()
        page = await client.pages.retrieve(page_id=page_id)
        return ToolResult(data=_format_page_summary(page))
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


@registry.tool(
    name="notion_read_page_content",
    description=(
        "Read the body content of a Notion page as plain text. "
        "Recursively reads nested blocks (toggles, etc.). "
        "Truncated at 50K characters for large pages."
    ),
    category="notion",
    params_model=NotionReadPageContentParams,
)
async def notion_read_page_content(page_id: str) -> ToolResult:
    try:
        client = _get_client()
        blocks_text = await _read_blocks_recursive(client, page_id)
        truncated = False
        if len(blocks_text) > MAX_CONTENT_CHARS:
            blocks_text = blocks_text[:MAX_CONTENT_CHARS]
            truncated = True
        return ToolResult(data={
            "page_id": page_id,
            "content": blocks_text,
            "truncated": truncated,
        })
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


async def _read_blocks_recursive(
    client: AsyncClient,
    block_id: str,
    depth: int = 0,
    max_depth: int = 5,
) -> str:
    """Recursively read all blocks under a parent, returning plain text."""
    if depth > max_depth:
        return ""
    lines: list[str] = []
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"block_id": block_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        response = await client.blocks.children.list(**kwargs)
        for block in response.get("results", []):
            text = _extract_block_text(block)
            indent = "  " * depth
            if text:
                lines.append(f"{indent}{text}")
            if block.get("has_children"):
                child_text = await _read_blocks_recursive(
                    client, block["id"], depth + 1, max_depth
                )
                if child_text:
                    lines.append(child_text)
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
    return "\n".join(lines)


@registry.tool(
    name="notion_create_page",
    description=(
        "Create a new page in a Notion database. Properties are auto-formatted "
        "based on the database schema — just pass simple values like "
        "{'Name': 'My Task', 'Status': 'Not Started', 'Due Date': '2025-03-15'}. "
        "Optionally include body text via the content parameter."
    ),
    category="notion",
    params_model=NotionCreatePageParams,
    requires_confirmation=True,
)
async def notion_create_page(
    database_id: str,
    properties: dict[str, Any],
    content: str | None = None,
) -> ToolResult:
    try:
        formatted_props = await _build_properties_payload(properties, database_id)
        client = _get_client()
        kwargs: dict[str, Any] = {
            "parent": {"database_id": database_id},
            "properties": formatted_props,
        }
        if content:
            kwargs["children"] = _text_to_blocks(content)
        page = await client.pages.create(**kwargs)
        return ToolResult(data=_format_page_summary(page))
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


@registry.tool(
    name="notion_update_page",
    description=(
        "Update properties of an existing Notion page. Only include the properties "
        "you want to change. Values are auto-formatted if the page belongs to a database."
    ),
    category="notion",
    params_model=NotionUpdatePageParams,
    requires_confirmation=True,
)
async def notion_update_page(
    page_id: str,
    properties: dict[str, Any],
) -> ToolResult:
    try:
        client = _get_client()
        # Retrieve the page to find its parent database for schema-aware formatting
        page = await client.pages.retrieve(page_id=page_id)
        parent = page.get("parent", {})
        db_id = parent.get("database_id")
        formatted_props = await _build_properties_payload(properties, db_id)
        updated = await client.pages.update(page_id=page_id, properties=formatted_props)
        return ToolResult(data=_format_page_summary(updated))
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


@registry.tool(
    name="notion_archive_page",
    description=(
        "Archive (soft-delete) a Notion page. The page can be restored from Notion's trash."
    ),
    category="notion",
    params_model=NotionArchivePageParams,
    requires_confirmation=True,
)
async def notion_archive_page(page_id: str) -> ToolResult:
    try:
        client = _get_client()
        page = await client.pages.update(page_id=page_id, archived=True)
        return ToolResult(data={"archived": True, "id": page["id"], "url": page.get("url", "")})
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


@registry.tool(
    name="notion_append_content",
    description=(
        "Append text to the body of a Notion page. The text is split into paragraph "
        "blocks on double newlines."
    ),
    category="notion",
    params_model=NotionAppendContentParams,
    requires_confirmation=True,
)
async def notion_append_content(page_id: str, content: str) -> ToolResult:
    try:
        client = _get_client()
        blocks = _text_to_blocks(content)
        if not blocks:
            return ToolResult(error="No content to append (empty or whitespace-only text).")
        response = await client.blocks.children.append(block_id=page_id, children=blocks)
        return ToolResult(data={
            "page_id": page_id,
            "blocks_added": len(response.get("results", [])),
        })
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))
