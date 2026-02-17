"""Notion tools — generic database and page CRUD."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from pydantic import Field, model_validator

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


_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.+)$")
_NUMBERED_RE = re.compile(r"^\d+\.\s+(.+)$")
_TODO_RE = re.compile(r"^-\s+\[([ xX])\]\s+(.+)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_DIVIDER_RE = re.compile(r"^(---|___|\*\*\*)$")
_CODE_FENCE_RE = re.compile(r"^```(\w*)$")


def _markdown_to_blocks(text: str) -> list[dict[str, Any]]:
    """Convert markdown text to Notion blocks.

    Supports headings (h1–h3), bulleted/numbered lists, to-do items,
    blockquotes, fenced code blocks, dividers, and plain paragraphs.
    """
    if not text:
        return []

    lines = text.split("\n")
    blocks: list[dict[str, Any]] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip blank lines
        if not stripped:
            i += 1
            continue

        # Fenced code block
        m = _CODE_FENCE_RE.match(stripped)
        if m:
            language = m.group(1) or "plain text"
            code_lines: list[str] = []
            i += 1
            while i < len(lines):
                if lines[i].strip() == "```":
                    i += 1
                    break
                code_lines.append(lines[i])
                i += 1
            blocks.append(
                {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": _plain_to_rich_text("\n".join(code_lines)),
                        "language": language,
                    },
                }
            )
            continue

        # Divider
        if _DIVIDER_RE.match(stripped):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # Heading
        m = _HEADING_RE.match(stripped)
        if m:
            level = len(m.group(1))
            heading_type = f"heading_{level}"
            blocks.append(
                {
                    "object": "block",
                    "type": heading_type,
                    heading_type: {"rich_text": _plain_to_rich_text(m.group(2))},
                }
            )
            i += 1
            continue

        # To-do (must be checked before bullet since `- [ ]` starts with `-`)
        m = _TODO_RE.match(stripped)
        if m:
            checked = m.group(1).lower() == "x"
            blocks.append(
                {
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": _plain_to_rich_text(m.group(2)),
                        "checked": checked,
                    },
                }
            )
            i += 1
            continue

        # Bulleted list item
        m = _BULLET_RE.match(stripped)
        if m:
            blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": _plain_to_rich_text(m.group(1))},
                }
            )
            i += 1
            continue

        # Numbered list item
        m = _NUMBERED_RE.match(stripped)
        if m:
            blocks.append(
                {
                    "object": "block",
                    "type": "numbered_list_item",
                    "numbered_list_item": {"rich_text": _plain_to_rich_text(m.group(1))},
                }
            )
            i += 1
            continue

        # Blockquote
        m = _QUOTE_RE.match(stripped)
        if m:
            blocks.append(
                {
                    "object": "block",
                    "type": "quote",
                    "quote": {"rich_text": _plain_to_rich_text(m.group(1))},
                }
            )
            i += 1
            continue

        # Plain paragraph — collect consecutive non-blank, non-special lines
        para_lines: list[str] = [stripped]
        i += 1
        while i < len(lines):
            next_stripped = lines[i].strip()
            if not next_stripped:
                break
            # Stop if the next line matches any block-level pattern
            if (
                _HEADING_RE.match(next_stripped)
                or _TODO_RE.match(next_stripped)
                or _BULLET_RE.match(next_stripped)
                or _NUMBERED_RE.match(next_stripped)
                or _QUOTE_RE.match(next_stripped)
                or _DIVIDER_RE.match(next_stripped)
                or _CODE_FENCE_RE.match(next_stripped)
            ):
                break
            para_lines.append(next_stripped)
            i += 1
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _plain_to_rich_text("\n".join(para_lines))},
            }
        )

    return blocks


# Backward compat — tests and existing callers import _text_to_blocks
_text_to_blocks = _markdown_to_blocks


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


# Block types that support rich_text updates
_RICH_TEXT_BLOCK_TYPES = frozenset(
    {
        "paragraph",
        "heading_1",
        "heading_2",
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "quote",
        "callout",
        "toggle",
        "to_do",
        "code",
    }
)


def _build_block_update_payload(
    block_type: str,
    content: str,
    *,
    checked: bool | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Build the type-specific payload for a block update PATCH request.

    Raises ``ValueError`` for unsupported block types.
    """
    if block_type not in _RICH_TEXT_BLOCK_TYPES:
        supported = ", ".join(sorted(_RICH_TEXT_BLOCK_TYPES))
        msg = f"Cannot update block type '{block_type}'. Supported types: {supported}"
        raise ValueError(msg)

    rich_text = _plain_to_rich_text(content)

    if block_type == "to_do":
        payload: dict[str, Any] = {"rich_text": rich_text}
        if checked is not None:
            payload["checked"] = checked
        return {"to_do": payload}

    if block_type == "code":
        code_payload: dict[str, Any] = {"rich_text": rich_text}
        if language is not None:
            code_payload["language"] = language
        return {"code": code_payload}

    return {block_type: {"rich_text": rich_text}}


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
        return [person.get("name", person.get("id", "")) for person in prop.get("people", [])]
    if ptype == "files":
        files = prop.get("files", [])
        return [f.get("name", f.get("external", {}).get("url", "")) for f in files]
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
    database_id: str | None = Field(
        default=None,
        description="The database to create the page in (mutually exclusive with page_id)",
    )
    page_id: str | None = Field(
        default=None,
        description=(
            "Parent page ID to create a child page under (mutually exclusive with database_id)"
        ),
    )
    properties: dict[str, Any] = Field(
        description=(
            "Page properties as {name: value}. For database parents, values are "
            "auto-formatted based on schema (e.g. {'Name': 'My Task', 'Status': 'Not Started'}). "
            "For page parents, only the title property is used (e.g. {'title': 'Child Page'})."
        ),
    )
    content: str | None = Field(
        default=None,
        description=(
            "Optional page body content (supports markdown: headings, bullets, "
            "numbered lists, to-do items, quotes, code blocks, dividers, paragraphs)"
        ),
    )

    @model_validator(mode="after")
    def _require_one_parent(self) -> NotionCreatePageParams:
        if self.database_id and self.page_id:
            msg = "Specify either database_id or page_id, not both."
            raise ValueError(msg)
        if not self.database_id and not self.page_id:
            msg = "Either database_id or page_id is required."
            raise ValueError(msg)
        return self


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
        description=(
            "Content to append (supports markdown: headings, bullets, "
            "numbered lists, to-do items, quotes, code blocks, dividers, paragraphs)"
        ),
    )
    after: str | None = Field(
        default=None,
        description=(
            "Block ID to insert after. When provided, new content is inserted "
            "after this block instead of at the end of the page."
        ),
    )


class NotionListBlocksParams(ToolParams):
    block_id: str = Field(
        description="The ID of the page or block whose children to list",
    )
    page_size: int = Field(
        default=100,
        description="Maximum blocks to return (1-100)",
        ge=1,
        le=100,
    )
    start_cursor: str | None = Field(
        default=None,
        description="Pagination cursor from a previous call's next_cursor",
    )


class NotionDeleteBlockParams(ToolParams):
    block_id: str = Field(description="The ID of the block to delete (archive)")


class NotionUpdateBlockParams(ToolParams):
    block_id: str = Field(description="The ID of the block to update")
    content: str = Field(description="New text content for the block")
    block_type: str | None = Field(
        default=None,
        description=(
            "Block type (e.g. 'paragraph', 'heading_1', 'to_do'). "
            "Auto-detected from the existing block if omitted."
        ),
    )
    checked: bool | None = Field(
        default=None,
        description="For to_do blocks: set the checked state",
    )
    language: str | None = Field(
        default=None,
        description="For code blocks: set the language (e.g. 'python', 'javascript')",
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
        return ToolResult(
            data={
                "results": results,
                "count": len(results),
                "has_more": response.get("has_more", False),
            }
        )
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
                    prop_info["options"] = [opt["name"] for opt in prop["select"]["options"]]
                elif ptype == "multi_select" and prop.get("multi_select", {}).get("options"):
                    prop_info["options"] = [opt["name"] for opt in prop["multi_select"]["options"]]
                elif ptype == "status" and prop.get("status", {}).get("options"):
                    prop_info["options"] = [opt["name"] for opt in prop["status"]["options"]]
                props[name] = prop_info
            databases.append(
                {
                    "id": db["id"],
                    "title": title,
                    "url": db.get("url", ""),
                    "properties": props,
                }
            )
        return ToolResult(
            data={
                "databases": databases,
                "count": len(databases),
                "has_more": response.get("has_more", False),
            }
        )
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
                prop_info["options"] = [opt["name"] for opt in prop["select"]["options"]]
            elif ptype == "multi_select" and prop.get("multi_select", {}).get("options"):
                prop_info["options"] = [opt["name"] for opt in prop["multi_select"]["options"]]
            elif ptype == "status" and prop.get("status", {}).get("options"):
                prop_info["options"] = [opt["name"] for opt in prop["status"]["options"]]
            props[name] = prop_info
        return ToolResult(
            data={
                "id": db["id"],
                "title": title,
                "url": db.get("url", ""),
                "properties": props,
            }
        )
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
        return ToolResult(
            data={
                "pages": pages,
                "count": len(pages),
                "has_more": response.get("has_more", False),
                "next_cursor": response.get("next_cursor"),
            }
        )
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
        return ToolResult(
            data={
                "page_id": page_id,
                "content": blocks_text,
                "truncated": truncated,
            }
        )
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
                child_text = await _read_blocks_recursive(client, block["id"], depth + 1, max_depth)
                if child_text:
                    lines.append(child_text)
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
    return "\n".join(lines)


@registry.tool(
    name="notion_create_page",
    description=(
        "Create a new page in a Notion database OR as a child of another page. "
        "Pass database_id to create inside a database (properties auto-formatted "
        "from schema), or page_id to create a child page under a regular page "
        "(only title property used, e.g. {'title': 'Child Page'}). "
        "Optionally include body content via the content parameter (supports markdown)."
    ),
    category="notion",
    params_model=NotionCreatePageParams,
    requires_confirmation=True,
)
async def notion_create_page(
    properties: dict[str, Any],
    database_id: str | None = None,
    page_id: str | None = None,
    content: str | None = None,
) -> ToolResult:
    try:
        client = _get_client()
        if database_id:
            formatted_props = await _build_properties_payload(properties, database_id)
            parent = {"database_id": database_id}
        else:
            # Child page under a regular page — format title property only
            title_text = None
            for key in ("title", "Title", "name", "Name"):
                if key in properties:
                    title_text = str(properties[key])
                    break
            if title_text is None:
                return ToolResult(
                    error=(
                        "Properties must include a title "
                        "(key: 'title', 'Title', 'name', or 'Name')."
                    )
                )
            formatted_props = {"title": {"title": _plain_to_rich_text(title_text)}}
            parent = {"page_id": page_id}
        kwargs: dict[str, Any] = {
            "parent": parent,
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
        "Append content to the body of a Notion page. "
        "Supports markdown: headings, bullets, numbered lists, "
        "to-do items, quotes, code blocks, dividers, and paragraphs. "
        "Optionally insert after a specific block (use notion_list_blocks to get block IDs)."
    ),
    category="notion",
    params_model=NotionAppendContentParams,
    requires_confirmation=True,
)
async def notion_append_content(
    page_id: str,
    content: str,
    after: str | None = None,
) -> ToolResult:
    try:
        client = _get_client()
        blocks = _text_to_blocks(content)
        if not blocks:
            return ToolResult(error="No content to append (empty or whitespace-only text).")
        kwargs: dict[str, Any] = {"block_id": page_id, "children": blocks}
        if after is not None:
            kwargs["after"] = after
        response = await client.blocks.children.append(**kwargs)
        return ToolResult(
            data={
                "page_id": page_id,
                "blocks_added": len(response.get("results", [])),
            }
        )
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


# ---------------------------------------------------------------------------
# Block-level tools
# ---------------------------------------------------------------------------


@registry.tool(
    name="notion_list_blocks",
    description=(
        "List child blocks of a Notion page or block. Returns block IDs, types, "
        "text content, and has_children flags. Use this to discover block IDs "
        "before updating or deleting individual blocks. Flat list only — call "
        "again with a child block's ID to drill down into nested content."
    ),
    category="notion",
    params_model=NotionListBlocksParams,
)
async def notion_list_blocks(
    block_id: str,
    page_size: int = 100,
    start_cursor: str | None = None,
) -> ToolResult:
    try:
        client = _get_client()
        kwargs: dict[str, Any] = {"block_id": block_id, "page_size": page_size}
        if start_cursor is not None:
            kwargs["start_cursor"] = start_cursor
        response = await client.blocks.children.list(**kwargs)
        blocks = []
        for block in response.get("results", []):
            blocks.append(
                {
                    "id": block["id"],
                    "type": block.get("type", ""),
                    "text": _extract_block_text(block),
                    "has_children": block.get("has_children", False),
                }
            )
        return ToolResult(
            data={
                "parent_id": block_id,
                "blocks": blocks,
                "count": len(blocks),
                "has_more": response.get("has_more", False),
                "next_cursor": response.get("next_cursor"),
            }
        )
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


@registry.tool(
    name="notion_delete_block",
    description=(
        "Delete (archive) a Notion block by ID. The block is soft-deleted "
        "and can be recovered from Notion's trash. Use notion_list_blocks "
        "to find block IDs."
    ),
    category="notion",
    params_model=NotionDeleteBlockParams,
    requires_confirmation=True,
)
async def notion_delete_block(block_id: str) -> ToolResult:
    try:
        client = _get_client()
        result = await client.blocks.delete(block_id=block_id)
        return ToolResult(
            data={
                "deleted": True,
                "id": result.get("id", block_id),
                "type": result.get("type", ""),
            }
        )
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


@registry.tool(
    name="notion_update_block",
    description=(
        "Update the text content of an existing Notion block. Supported types: "
        "paragraph, heading_1-3, bulleted/numbered_list_item, quote, callout, "
        "toggle, to_do, code. Use notion_list_blocks to find block IDs. "
        "Block type is auto-detected if not provided."
    ),
    category="notion",
    params_model=NotionUpdateBlockParams,
    requires_confirmation=True,
)
async def notion_update_block(
    block_id: str,
    content: str,
    block_type: str | None = None,
    checked: bool | None = None,
    language: str | None = None,
) -> ToolResult:
    try:
        client = _get_client()
        # Auto-detect block type if not provided
        if block_type is None:
            existing = await client.blocks.retrieve(block_id=block_id)
            block_type = existing.get("type", "")
        payload = _build_block_update_payload(
            block_type, content, checked=checked, language=language
        )
        updated = await client.blocks.update(block_id=block_id, **payload)
        return ToolResult(
            data={
                "id": updated.get("id", block_id),
                "type": updated.get("type", block_type),
                "text": _extract_block_text(updated),
            }
        )
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


# ---------------------------------------------------------------------------
# Create database
# ---------------------------------------------------------------------------


def _build_schema_payload(properties: dict[str, Any]) -> dict[str, Any]:
    """Convert simplified property definitions to Notion database schema format.

    Accepts a dict like::

        {"Name": "title", "Status": {"select": ["Todo", "Done"]}, "Due": "date"}

    Returns Notion-API-formatted property schema.
    """
    schema: dict[str, Any] = {}
    for name, definition in properties.items():
        if isinstance(definition, str):
            # Simple type shorthand: "title", "rich_text", "number", etc.
            schema[name] = {definition: {}}
        elif isinstance(definition, dict):
            # Expanded definition with options
            for ptype, options in definition.items():
                if ptype in ("select", "multi_select") and isinstance(options, list):
                    schema[name] = {ptype: {"options": [{"name": str(o)} for o in options]}}
                elif ptype == "status" and isinstance(options, list):
                    schema[name] = {"status": {"options": [{"name": str(o)} for o in options]}}
                else:
                    schema[name] = {ptype: options if options else {}}
                break  # Only the first key matters
        else:
            schema[name] = {"rich_text": {}}
    return schema


class NotionCreateDatabaseParams(ToolParams):
    page_id: str = Field(
        description="Parent page ID — the database will be created inside this page",
    )
    title: str = Field(description="Database title")
    properties: dict[str, Any] = Field(
        description=(
            "Database schema as {name: type_or_config}. "
            "Simple types: 'title', 'rich_text', 'number', 'date', "
            "'checkbox', 'url', 'email'. "
            "With options: {'select': ['Option A', 'Option B']}, "
            "{'multi_select': ['Tag1', 'Tag2']}."
        ),
    )
    is_inline: bool = Field(
        default=True,
        description=(
            "If true, creates an inline database (embedded in page). "
            "If false, creates a full-page database."
        ),
    )


@registry.tool(
    name="notion_create_database",
    description=(
        "Create a new database inside a Notion page. Define the schema with a "
        "simplified format: {'Name': 'title', 'Status': {'select': ['Todo', 'Done']}, "
        "'Due Date': 'date'}. The database is created inline by default."
    ),
    category="notion",
    params_model=NotionCreateDatabaseParams,
    requires_confirmation=True,
)
async def notion_create_database(
    page_id: str,
    title: str,
    properties: dict[str, Any],
    is_inline: bool = True,
) -> ToolResult:
    try:
        client = _get_client()
        schema = _build_schema_payload(properties)
        # Ensure there's exactly one title property
        has_title = any("title" in prop_def for prop_def in schema.values())
        if not has_title:
            schema["Name"] = {"title": {}}

        body: dict[str, Any] = {
            "parent": {"page_id": page_id},
            "title": _plain_to_rich_text(title),
            "properties": schema,
            "is_inline": is_inline,
        }
        # Use client.request() — same pattern as notion_query_database
        response = await client.request(
            path="databases",
            method="POST",
            body=body,
        )
        # Format response
        title_parts = response.get("title", [])
        db_title = _rich_text_to_plain(title_parts)
        props = {}
        for name, prop in response.get("properties", {}).items():
            props[name] = {"type": prop.get("type", "")}
        return ToolResult(
            data={
                "id": response["id"],
                "title": db_title,
                "url": response.get("url", ""),
                "properties": props,
            }
        )
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except Exception as exc:
        return ToolResult(error=_notion_error_message(exc))


# ---------------------------------------------------------------------------
# Future work
# ---------------------------------------------------------------------------
# - notion_list_comments + notion_create_comment — comments API
# - notion_update_database — modify database schema/title
# - Inline markdown formatting (bold, italic, links within rich text)
