"""Tests for src/tools/notion_tools."""

import pytest
from unittest.mock import AsyncMock, patch

from src.tools.notion_tools import (
    MAX_CONTENT_CHARS,
    RICH_TEXT_CHAR_LIMIT,
    NotionCreatePageParams,
    _build_properties_payload,
    _build_schema_payload,
    _extract_block_text,
    _format_page_properties,
    _format_page_summary,
    _format_property_value,
    _format_value_for_type,
    _markdown_to_blocks,
    _notion_error_message,
    _plain_to_rich_text,
    _read_blocks_recursive,
    _rich_text_to_plain,
    _text_to_blocks,
    notion_append_content,
    notion_archive_page,
    notion_create_database,
    notion_create_page,
    notion_get_database,
    notion_get_page,
    notion_list_databases,
    notion_query_database,
    notion_read_page_content,
    notion_search,
    notion_update_page,
)

# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------


def _mock_client():
    """Return an AsyncMock pretending to be a Notion AsyncClient."""
    client = AsyncMock()
    client.search = AsyncMock()
    client.request = AsyncMock()
    client.databases = AsyncMock()
    client.databases.retrieve = AsyncMock()
    client.pages = AsyncMock()
    client.pages.retrieve = AsyncMock()
    client.pages.create = AsyncMock()
    client.pages.update = AsyncMock()
    client.blocks = AsyncMock()
    client.blocks.children = AsyncMock()
    client.blocks.children.list = AsyncMock()
    client.blocks.children.append = AsyncMock()
    return client


def _make_page(
    page_id: str = "page-123",
    title: str = "Test Page",
    **extra_properties,
) -> dict:
    """Create a minimal Notion page object."""
    properties = {
        "Name": {
            "type": "title",
            "title": [{"plain_text": title}],
        },
        **extra_properties,
    }
    return {
        "id": page_id,
        "object": "page",
        "url": f"https://www.notion.so/{page_id}",
        "archived": False,
        "created_time": "2025-01-01T00:00:00.000Z",
        "last_edited_time": "2025-01-02T00:00:00.000Z",
        "properties": properties,
        "parent": {"database_id": "db-456"},
    }


def _make_db(
    db_id: str = "db-456",
    title: str = "Tasks",
    properties: dict | None = None,
) -> dict:
    """Create a minimal Notion database object."""
    if properties is None:
        properties = {
            "Name": {"type": "title", "title": {}},
            "Status": {
                "type": "status",
                "status": {
                    "options": [
                        {"name": "Not Started"},
                        {"name": "In Progress"},
                        {"name": "Done"},
                    ],
                },
            },
        }
    return {
        "id": db_id,
        "object": "database",
        "title": [{"plain_text": title}],
        "url": f"https://www.notion.so/{db_id}",
        "properties": properties,
    }


# ---------------------------------------------------------------------------
# Rich text helpers
# ---------------------------------------------------------------------------


class TestRichTextToPlain:
    def test_empty_list(self) -> None:
        assert _rich_text_to_plain([]) == ""

    def test_single_element(self) -> None:
        rt = [{"plain_text": "Hello"}]
        assert _rich_text_to_plain(rt) == "Hello"

    def test_multiple_elements(self) -> None:
        rt = [{"plain_text": "Hello "}, {"plain_text": "world"}]
        assert _rich_text_to_plain(rt) == "Hello world"

    def test_missing_plain_text(self) -> None:
        rt = [{"type": "text"}]
        assert _rich_text_to_plain(rt) == ""


class TestPlainToRichText:
    def test_empty_string(self) -> None:
        assert _plain_to_rich_text("") == []

    def test_short_string(self) -> None:
        result = _plain_to_rich_text("Hello")
        assert len(result) == 1
        assert result[0]["text"]["content"] == "Hello"
        assert result[0]["type"] == "text"

    def test_long_string_splits(self) -> None:
        text = "x" * (RICH_TEXT_CHAR_LIMIT + 500)
        result = _plain_to_rich_text(text)
        assert len(result) == 2
        assert len(result[0]["text"]["content"]) == RICH_TEXT_CHAR_LIMIT
        assert len(result[1]["text"]["content"]) == 500

    def test_exact_limit(self) -> None:
        text = "x" * RICH_TEXT_CHAR_LIMIT
        result = _plain_to_rich_text(text)
        assert len(result) == 1


class TestTextToBlocks:
    def test_empty_string(self) -> None:
        assert _text_to_blocks("") == []

    def test_single_paragraph(self) -> None:
        blocks = _text_to_blocks("Hello world")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "paragraph"
        rt = blocks[0]["paragraph"]["rich_text"]
        assert rt[0]["text"]["content"] == "Hello world"

    def test_multiple_paragraphs(self) -> None:
        blocks = _text_to_blocks("First paragraph\n\nSecond paragraph")
        assert len(blocks) == 2

    def test_skips_blank_paragraphs(self) -> None:
        blocks = _text_to_blocks("First\n\n\n\nSecond")
        assert len(blocks) == 2

    def test_whitespace_only(self) -> None:
        assert _text_to_blocks("   \n\n   ") == []


class TestExtractBlockText:
    def test_paragraph_block(self) -> None:
        block = {
            "type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": "Hello"}]},
        }
        assert _extract_block_text(block) == "Hello"

    def test_heading_block(self) -> None:
        block = {
            "type": "heading_1",
            "heading_1": {"rich_text": [{"plain_text": "Title"}]},
        }
        assert _extract_block_text(block) == "Title"

    def test_empty_block(self) -> None:
        block = {"type": "divider", "divider": {}}
        assert _extract_block_text(block) == ""

    def test_child_page_with_title(self) -> None:
        block = {
            "type": "child_page",
            "child_page": {"title": "Sub Page"},
        }
        assert _extract_block_text(block) == "Sub Page"


# ---------------------------------------------------------------------------
# Property formatting
# ---------------------------------------------------------------------------


class TestFormatPropertyValue:
    def test_title(self) -> None:
        prop = {"type": "title", "title": [{"plain_text": "My Title"}]}
        assert _format_property_value(prop) == "My Title"

    def test_rich_text(self) -> None:
        prop = {"type": "rich_text", "rich_text": [{"plain_text": "Notes"}]}
        assert _format_property_value(prop) == "Notes"

    def test_number(self) -> None:
        prop = {"type": "number", "number": 42}
        assert _format_property_value(prop) == 42

    def test_number_none(self) -> None:
        prop = {"type": "number", "number": None}
        assert _format_property_value(prop) is None

    def test_select(self) -> None:
        prop = {"type": "select", "select": {"name": "High"}}
        assert _format_property_value(prop) == "High"

    def test_select_none(self) -> None:
        prop = {"type": "select", "select": None}
        assert _format_property_value(prop) is None

    def test_multi_select(self) -> None:
        prop = {
            "type": "multi_select",
            "multi_select": [{"name": "Tag1"}, {"name": "Tag2"}],
        }
        assert _format_property_value(prop) == ["Tag1", "Tag2"]

    def test_status(self) -> None:
        prop = {"type": "status", "status": {"name": "In Progress"}}
        assert _format_property_value(prop) == "In Progress"

    def test_status_none(self) -> None:
        prop = {"type": "status", "status": None}
        assert _format_property_value(prop) is None

    def test_date_with_start_only(self) -> None:
        prop = {"type": "date", "date": {"start": "2025-03-15"}}
        assert _format_property_value(prop) == {"start": "2025-03-15"}

    def test_date_with_end(self) -> None:
        prop = {"type": "date", "date": {"start": "2025-03-15", "end": "2025-03-16"}}
        assert _format_property_value(prop) == {"start": "2025-03-15", "end": "2025-03-16"}

    def test_date_none(self) -> None:
        prop = {"type": "date", "date": None}
        assert _format_property_value(prop) is None

    def test_checkbox(self) -> None:
        prop = {"type": "checkbox", "checkbox": True}
        assert _format_property_value(prop) is True

    def test_url(self) -> None:
        prop = {"type": "url", "url": "https://example.com"}
        assert _format_property_value(prop) == "https://example.com"

    def test_email(self) -> None:
        prop = {"type": "email", "email": "a@b.com"}
        assert _format_property_value(prop) == "a@b.com"

    def test_phone_number(self) -> None:
        prop = {"type": "phone_number", "phone_number": "+15551234"}
        assert _format_property_value(prop) == "+15551234"

    def test_formula(self) -> None:
        prop = {"type": "formula", "formula": {"type": "string", "string": "computed"}}
        assert _format_property_value(prop) == "computed"

    def test_relation(self) -> None:
        prop = {"type": "relation", "relation": [{"id": "page1"}, {"id": "page2"}]}
        assert _format_property_value(prop) == ["page1", "page2"]

    def test_people(self) -> None:
        prop = {"type": "people", "people": [{"name": "Alice"}, {"id": "user2"}]}
        assert _format_property_value(prop) == ["Alice", "user2"]

    def test_files(self) -> None:
        prop = {"type": "files", "files": [{"name": "report.pdf"}]}
        assert _format_property_value(prop) == ["report.pdf"]

    def test_unique_id_with_prefix(self) -> None:
        prop = {"type": "unique_id", "unique_id": {"prefix": "TASK", "number": 42}}
        assert _format_property_value(prop) == "TASK-42"

    def test_unique_id_no_prefix(self) -> None:
        prop = {"type": "unique_id", "unique_id": {"prefix": "", "number": 7}}
        assert _format_property_value(prop) == "7"

    def test_created_time(self) -> None:
        prop = {"type": "created_time", "created_time": "2025-01-01T00:00:00.000Z"}
        assert _format_property_value(prop) == "2025-01-01T00:00:00.000Z"

    def test_last_edited_time(self) -> None:
        prop = {"type": "last_edited_time", "last_edited_time": "2025-01-02T00:00:00.000Z"}
        assert _format_property_value(prop) == "2025-01-02T00:00:00.000Z"

    def test_created_by(self) -> None:
        prop = {"type": "created_by", "created_by": {"name": "Alice"}}
        assert _format_property_value(prop) == "Alice"

    def test_last_edited_by(self) -> None:
        prop = {"type": "last_edited_by", "last_edited_by": {"id": "user1"}}
        assert _format_property_value(prop) == "user1"

    def test_rollup(self) -> None:
        prop = {"type": "rollup", "rollup": {"type": "number", "number": 10}}
        assert _format_property_value(prop) == 10

    def test_unknown_type(self) -> None:
        prop = {"type": "custom_thing", "custom_thing": "data"}
        result = _format_property_value(prop)
        assert isinstance(result, str)


class TestFormatPageProperties:
    def test_formats_all(self) -> None:
        properties = {
            "Name": {"type": "title", "title": [{"plain_text": "Task 1"}]},
            "Status": {"type": "status", "status": {"name": "Done"}},
        }
        result = _format_page_properties(properties)
        assert result["Name"] == "Task 1"
        assert result["Status"] == "Done"


class TestFormatPageSummary:
    def test_includes_expected_fields(self) -> None:
        page = _make_page()
        summary = _format_page_summary(page)
        assert summary["id"] == "page-123"
        assert summary["url"].startswith("https://")
        assert summary["archived"] is False
        assert "created_time" in summary
        assert "last_edited_time" in summary
        assert summary["properties"]["Name"] == "Test Page"


# ---------------------------------------------------------------------------
# _format_value_for_type
# ---------------------------------------------------------------------------


class TestFormatValueForType:
    def test_title(self) -> None:
        result = _format_value_for_type("title", "Hello")
        assert result["title"][0]["text"]["content"] == "Hello"

    def test_rich_text(self) -> None:
        result = _format_value_for_type("rich_text", "Notes here")
        assert result["rich_text"][0]["text"]["content"] == "Notes here"

    def test_number(self) -> None:
        assert _format_value_for_type("number", 42) == {"number": 42}

    def test_select(self) -> None:
        assert _format_value_for_type("select", "High") == {"select": {"name": "High"}}

    def test_select_none(self) -> None:
        assert _format_value_for_type("select", None) == {"select": None}

    def test_multi_select_list(self) -> None:
        result = _format_value_for_type("multi_select", ["A", "B"])
        assert result == {"multi_select": [{"name": "A"}, {"name": "B"}]}

    def test_multi_select_single(self) -> None:
        result = _format_value_for_type("multi_select", "A")
        assert result == {"multi_select": [{"name": "A"}]}

    def test_status(self) -> None:
        assert _format_value_for_type("status", "Done") == {"status": {"name": "Done"}}

    def test_status_none(self) -> None:
        assert _format_value_for_type("status", None) == {"status": None}

    def test_date_string(self) -> None:
        result = _format_value_for_type("date", "2025-03-15")
        assert result == {"date": {"start": "2025-03-15"}}

    def test_date_dict(self) -> None:
        val = {"start": "2025-03-15", "end": "2025-03-16"}
        result = _format_value_for_type("date", val)
        assert result == {"date": val}

    def test_date_none(self) -> None:
        assert _format_value_for_type("date", None) == {"date": None}

    def test_checkbox(self) -> None:
        assert _format_value_for_type("checkbox", True) == {"checkbox": True}

    def test_url(self) -> None:
        assert _format_value_for_type("url", "https://x.com") == {"url": "https://x.com"}

    def test_url_none(self) -> None:
        assert _format_value_for_type("url", None) == {"url": None}

    def test_email(self) -> None:
        assert _format_value_for_type("email", "a@b.com") == {"email": "a@b.com"}

    def test_phone_number(self) -> None:
        result = _format_value_for_type("phone_number", "+1555")
        assert result == {"phone_number": "+1555"}

    def test_relation_list(self) -> None:
        result = _format_value_for_type("relation", ["id1", "id2"])
        assert result == {"relation": [{"id": "id1"}, {"id": "id2"}]}

    def test_relation_single(self) -> None:
        result = _format_value_for_type("relation", "id1")
        assert result == {"relation": [{"id": "id1"}]}

    def test_people_list(self) -> None:
        result = _format_value_for_type("people", ["u1", "u2"])
        assert result == {"people": [{"id": "u1"}, {"id": "u2"}]}

    def test_unknown_type_passthrough(self) -> None:
        result = _format_value_for_type("formula", "computed")
        assert result == {"formula": "computed"}


# ---------------------------------------------------------------------------
# _build_properties_payload
# ---------------------------------------------------------------------------


class TestBuildPropertiesPayload:
    async def test_without_database_id_passthrough(self) -> None:
        props = {"Name": {"title": [{"text": {"content": "Hello"}}]}}
        result = await _build_properties_payload(props, database_id=None)
        assert result == props

    async def test_with_database_id_formats_values(self) -> None:
        db = _make_db(properties={
            "Name": {"type": "title", "title": {}},
            "Status": {
                "type": "status",
                "status": {"options": [{"name": "Done"}]},
            },
        })
        client = _mock_client()
        client.databases.retrieve.return_value = db

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await _build_properties_payload(
                {"Name": "My Task", "Status": "Done"},
                database_id="db-456",
            )

        assert result["Name"]["title"][0]["text"]["content"] == "My Task"
        assert result["Status"] == {"status": {"name": "Done"}}

    async def test_unknown_property_passthrough(self) -> None:
        db = _make_db(properties={"Name": {"type": "title", "title": {}}})
        client = _mock_client()
        client.databases.retrieve.return_value = db

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await _build_properties_payload(
                {"Name": "Hello", "Unknown": "raw_value"},
                database_id="db-456",
            )

        assert result["Unknown"] == "raw_value"


# ---------------------------------------------------------------------------
# _notion_error_message
# ---------------------------------------------------------------------------


class TestNotionErrorMessage:
    def test_with_message_attr(self) -> None:
        exc = Exception("generic")
        exc.message = "Not found"  # type: ignore[attr-defined]
        assert _notion_error_message(exc) == "Not found"

    def test_without_message_attr(self) -> None:
        exc = ValueError("something broke")
        assert _notion_error_message(exc) == "something broke"


# ---------------------------------------------------------------------------
# notion_search
# ---------------------------------------------------------------------------


class TestNotionSearch:
    async def test_success(self) -> None:
        page = _make_page()
        client = _mock_client()
        client.search.return_value = {"results": [page], "has_more": False}

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_search(query="Test")

        assert result.success
        assert result.data["count"] == 1
        assert result.data["results"][0]["id"] == "page-123"
        client.search.assert_awaited_once()

    async def test_with_filter_type(self) -> None:
        client = _mock_client()
        client.search.return_value = {"results": [], "has_more": False}

        with patch("src.tools.notion_tools._get_client", return_value=client):
            await notion_search(query="Test", filter_type="page")

        call_kwargs = client.search.call_args.kwargs
        assert call_kwargs["filter"] == {"value": "page", "property": "object"}

    async def test_invalid_filter_type_ignored(self) -> None:
        client = _mock_client()
        client.search.return_value = {"results": [], "has_more": False}

        with patch("src.tools.notion_tools._get_client", return_value=client):
            await notion_search(query="Test", filter_type="invalid")

        call_kwargs = client.search.call_args.kwargs
        assert "filter" not in call_kwargs

    async def test_missing_config(self) -> None:
        with patch("src.tools.notion_tools._get_client", side_effect=ValueError("not configured")):
            result = await notion_search(query="Test")
        assert not result.success
        assert "not configured" in result.error

    async def test_api_error(self) -> None:
        exc = Exception("API error")
        exc.message = "Rate limited"  # type: ignore[attr-defined]
        client = _mock_client()
        client.search.side_effect = exc

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_search(query="Test")

        assert not result.success
        assert "Rate limited" in result.error


# ---------------------------------------------------------------------------
# notion_list_databases
# ---------------------------------------------------------------------------


class TestNotionListDatabases:
    async def test_success(self) -> None:
        db = _make_db()
        client = _mock_client()
        client.search.return_value = {"results": [db], "has_more": False}

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_list_databases()

        assert result.success
        assert result.data["count"] == 1
        assert result.data["databases"][0]["title"] == "Tasks"
        assert "Status" in result.data["databases"][0]["properties"]

    async def test_includes_select_options(self) -> None:
        db = _make_db(properties={
            "Priority": {
                "type": "select",
                "select": {"options": [{"name": "High"}, {"name": "Low"}]},
            },
        })
        client = _mock_client()
        client.search.return_value = {"results": [db], "has_more": False}

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_list_databases()

        props = result.data["databases"][0]["properties"]
        assert props["Priority"]["options"] == ["High", "Low"]

    async def test_missing_config(self) -> None:
        with patch("src.tools.notion_tools._get_client", side_effect=ValueError("no key")):
            result = await notion_list_databases()
        assert not result.success


# ---------------------------------------------------------------------------
# notion_get_database
# ---------------------------------------------------------------------------


class TestNotionGetDatabase:
    async def test_success(self) -> None:
        db = _make_db()
        client = _mock_client()
        client.databases.retrieve.return_value = db

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_get_database(database_id="db-456")

        assert result.success
        assert result.data["title"] == "Tasks"
        assert "Status" in result.data["properties"]

    async def test_api_error(self) -> None:
        exc = Exception("not found")
        exc.message = "Database not found"  # type: ignore[attr-defined]
        client = _mock_client()
        client.databases.retrieve.side_effect = exc

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_get_database(database_id="bad-id")

        assert not result.success
        assert "not found" in result.error


# ---------------------------------------------------------------------------
# notion_query_database
# ---------------------------------------------------------------------------


class TestNotionQueryDatabase:
    async def test_success(self) -> None:
        page = _make_page()
        client = _mock_client()
        client.request.return_value = {
            "results": [page],
            "has_more": True,
            "next_cursor": "cursor-abc",
        }

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_query_database(database_id="db-456")

        assert result.success
        assert result.data["count"] == 1
        assert result.data["has_more"] is True
        assert result.data["next_cursor"] == "cursor-abc"

    async def test_with_filter_and_sorts(self) -> None:
        client = _mock_client()
        client.request.return_value = {"results": [], "has_more": False}
        test_filter = {"property": "Status", "status": {"equals": "Done"}}
        test_sorts = [{"property": "Due Date", "direction": "ascending"}]

        with patch("src.tools.notion_tools._get_client", return_value=client):
            await notion_query_database(
                database_id="db-456",
                filter=test_filter,
                sorts=test_sorts,
            )

        call_kwargs = client.request.call_args.kwargs
        assert call_kwargs["body"]["filter"] == test_filter
        assert call_kwargs["body"]["sorts"] == test_sorts

    async def test_with_pagination(self) -> None:
        client = _mock_client()
        client.request.return_value = {"results": [], "has_more": False}

        with patch("src.tools.notion_tools._get_client", return_value=client):
            await notion_query_database(
                database_id="db-456",
                start_cursor="cursor-xyz",
            )

        call_kwargs = client.request.call_args.kwargs
        assert call_kwargs["body"]["start_cursor"] == "cursor-xyz"

    async def test_api_error(self) -> None:
        exc = Exception("bad query")
        exc.message = "Invalid filter"  # type: ignore[attr-defined]
        client = _mock_client()
        client.request.side_effect = exc

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_query_database(database_id="db-456")

        assert not result.success


# ---------------------------------------------------------------------------
# notion_get_page
# ---------------------------------------------------------------------------


class TestNotionGetPage:
    async def test_success(self) -> None:
        page = _make_page()
        client = _mock_client()
        client.pages.retrieve.return_value = page

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_get_page(page_id="page-123")

        assert result.success
        assert result.data["id"] == "page-123"
        assert result.data["properties"]["Name"] == "Test Page"

    async def test_not_found(self) -> None:
        exc = Exception("not found")
        exc.message = "Page not found"  # type: ignore[attr-defined]
        client = _mock_client()
        client.pages.retrieve.side_effect = exc

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_get_page(page_id="bad-id")

        assert not result.success


# ---------------------------------------------------------------------------
# notion_read_page_content
# ---------------------------------------------------------------------------


class TestNotionReadPageContent:
    async def test_simple_content(self) -> None:
        client = _mock_client()
        client.blocks.children.list.return_value = {
            "results": [
                {
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"plain_text": "Hello world"}]},
                    "has_children": False,
                },
            ],
            "has_more": False,
        }

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_read_page_content(page_id="page-123")

        assert result.success
        assert "Hello world" in result.data["content"]
        assert result.data["truncated"] is False

    async def test_nested_blocks(self) -> None:
        client = _mock_client()
        # First call: top-level blocks
        top_response = {
            "results": [
                {
                    "id": "block-1",
                    "type": "toggle",
                    "toggle": {"rich_text": [{"plain_text": "Toggle"}]},
                    "has_children": True,
                },
            ],
            "has_more": False,
        }
        # Second call: child blocks
        child_response = {
            "results": [
                {
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"plain_text": "Inside toggle"}]},
                    "has_children": False,
                },
            ],
            "has_more": False,
        }
        client.blocks.children.list.side_effect = [top_response, child_response]

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_read_page_content(page_id="page-123")

        assert result.success
        assert "Toggle" in result.data["content"]
        assert "Inside toggle" in result.data["content"]

    async def test_pagination(self) -> None:
        client = _mock_client()
        page1 = {
            "results": [
                {
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"plain_text": "First"}]},
                    "has_children": False,
                },
            ],
            "has_more": True,
            "next_cursor": "cursor-2",
        }
        page2 = {
            "results": [
                {
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"plain_text": "Second"}]},
                    "has_children": False,
                },
            ],
            "has_more": False,
        }
        client.blocks.children.list.side_effect = [page1, page2]

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_read_page_content(page_id="page-123")

        assert result.success
        assert "First" in result.data["content"]
        assert "Second" in result.data["content"]

    async def test_truncation(self) -> None:
        long_text = "x" * (MAX_CONTENT_CHARS + 100)
        client = _mock_client()
        client.blocks.children.list.return_value = {
            "results": [
                {
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"plain_text": long_text}]},
                    "has_children": False,
                },
            ],
            "has_more": False,
        }

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_read_page_content(page_id="page-123")

        assert result.success
        assert result.data["truncated"] is True
        assert len(result.data["content"]) == MAX_CONTENT_CHARS

    async def test_api_error(self) -> None:
        exc = Exception("error")
        exc.message = "Access denied"  # type: ignore[attr-defined]
        client = _mock_client()
        client.blocks.children.list.side_effect = exc

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_read_page_content(page_id="page-123")

        assert not result.success


# ---------------------------------------------------------------------------
# _read_blocks_recursive
# ---------------------------------------------------------------------------


class TestReadBlocksRecursive:
    async def test_max_depth_returns_empty(self) -> None:
        client = _mock_client()
        result = await _read_blocks_recursive(client, "block-id", depth=6, max_depth=5)
        assert result == ""
        client.blocks.children.list.assert_not_awaited()


# ---------------------------------------------------------------------------
# notion_create_page
# ---------------------------------------------------------------------------


class TestNotionCreatePage:
    async def test_basic_create(self) -> None:
        page = _make_page()
        db = _make_db()
        client = _mock_client()
        client.databases.retrieve.return_value = db
        client.pages.create.return_value = page

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_create_page(
                database_id="db-456",
                properties={"Name": "New Task"},
            )

        assert result.success
        assert result.data["id"] == "page-123"
        client.pages.create.assert_awaited_once()

    async def test_create_with_content(self) -> None:
        page = _make_page()
        db = _make_db()
        client = _mock_client()
        client.databases.retrieve.return_value = db
        client.pages.create.return_value = page

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_create_page(
                database_id="db-456",
                properties={"Name": "New Task"},
                content="Some body text\n\nSecond paragraph",
            )

        assert result.success
        create_kwargs = client.pages.create.call_args.kwargs
        assert "children" in create_kwargs
        assert len(create_kwargs["children"]) == 2

    async def test_api_error(self) -> None:
        db = _make_db()
        exc = Exception("error")
        exc.message = "Validation error"  # type: ignore[attr-defined]
        client = _mock_client()
        client.databases.retrieve.return_value = db
        client.pages.create.side_effect = exc

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_create_page(
                database_id="db-456",
                properties={"Name": "Test"},
            )

        assert not result.success

    async def test_missing_config(self) -> None:
        with patch("src.tools.notion_tools._get_client", side_effect=ValueError("no key")):
            result = await notion_create_page(
                database_id="db-456",
                properties={"Name": "Test"},
            )
        assert not result.success


# ---------------------------------------------------------------------------
# notion_update_page
# ---------------------------------------------------------------------------


class TestNotionUpdatePage:
    async def test_success(self) -> None:
        page = _make_page()
        db = _make_db()
        updated_page = {**page, "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Updated"}]},
        }}
        client = _mock_client()
        client.pages.retrieve.return_value = page
        client.databases.retrieve.return_value = db
        client.pages.update.return_value = updated_page

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_update_page(
                page_id="page-123",
                properties={"Name": "Updated"},
            )

        assert result.success
        client.pages.update.assert_awaited_once()

    async def test_page_without_database_parent(self) -> None:
        page = _make_page()
        page["parent"] = {"workspace": True}
        updated_page = {**page}
        client = _mock_client()
        client.pages.retrieve.return_value = page
        client.pages.update.return_value = updated_page

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_update_page(
                page_id="page-123",
                properties={"Name": {"title": [{"text": {"content": "Manual"}}]}},
            )

        assert result.success

    async def test_api_error(self) -> None:
        exc = Exception("error")
        exc.message = "Cannot update"  # type: ignore[attr-defined]
        client = _mock_client()
        client.pages.retrieve.side_effect = exc

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_update_page(
                page_id="page-123",
                properties={"Status": "Done"},
            )

        assert not result.success


# ---------------------------------------------------------------------------
# notion_archive_page
# ---------------------------------------------------------------------------


class TestNotionArchivePage:
    async def test_success(self) -> None:
        page = _make_page()
        page["archived"] = True
        client = _mock_client()
        client.pages.update.return_value = page

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_archive_page(page_id="page-123")

        assert result.success
        assert result.data["archived"] is True
        client.pages.update.assert_awaited_once_with(page_id="page-123", archived=True)

    async def test_api_error(self) -> None:
        exc = Exception("error")
        exc.message = "Not found"  # type: ignore[attr-defined]
        client = _mock_client()
        client.pages.update.side_effect = exc

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_archive_page(page_id="bad-id")

        assert not result.success


# ---------------------------------------------------------------------------
# notion_append_content
# ---------------------------------------------------------------------------


class TestNotionAppendContent:
    async def test_success(self) -> None:
        client = _mock_client()
        client.blocks.children.append.return_value = {
            "results": [{"id": "block-new", "type": "paragraph"}],
        }

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_append_content(
                page_id="page-123",
                content="New paragraph\n\nAnother one",
            )

        assert result.success
        assert result.data["blocks_added"] == 1
        client.blocks.children.append.assert_awaited_once()

    async def test_empty_content(self) -> None:
        with patch("src.tools.notion_tools._get_client", return_value=_mock_client()):
            result = await notion_append_content(
                page_id="page-123",
                content="   ",
            )

        assert not result.success
        assert "empty" in result.error.lower()

    async def test_api_error(self) -> None:
        exc = Exception("error")
        exc.message = "Append failed"  # type: ignore[attr-defined]
        client = _mock_client()
        client.blocks.children.append.side_effect = exc

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_append_content(
                page_id="page-123",
                content="Some text",
            )

        assert not result.success

    async def test_missing_config(self) -> None:
        with patch("src.tools.notion_tools._get_client", side_effect=ValueError("no key")):
            result = await notion_append_content(
                page_id="page-123",
                content="text",
            )
        assert not result.success


# ---------------------------------------------------------------------------
# _markdown_to_blocks
# ---------------------------------------------------------------------------


class TestMarkdownToBlocks:
    def test_empty_string(self) -> None:
        assert _markdown_to_blocks("") == []

    def test_alias_matches(self) -> None:
        """_text_to_blocks should be an alias for _markdown_to_blocks."""
        assert _text_to_blocks is _markdown_to_blocks

    def test_plain_paragraph(self) -> None:
        blocks = _markdown_to_blocks("Hello world")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "paragraph"
        assert blocks[0]["paragraph"]["rich_text"][0]["text"]["content"] == "Hello world"

    def test_multiple_paragraphs(self) -> None:
        blocks = _markdown_to_blocks("First paragraph\n\nSecond paragraph")
        assert len(blocks) == 2
        assert blocks[0]["type"] == "paragraph"
        assert blocks[1]["type"] == "paragraph"

    def test_heading_1(self) -> None:
        blocks = _markdown_to_blocks("# Main Title")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "heading_1"
        assert blocks[0]["heading_1"]["rich_text"][0]["text"]["content"] == "Main Title"

    def test_heading_2(self) -> None:
        blocks = _markdown_to_blocks("## Section")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "heading_2"

    def test_heading_3(self) -> None:
        blocks = _markdown_to_blocks("### Subsection")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "heading_3"

    def test_bulleted_list_dash(self) -> None:
        blocks = _markdown_to_blocks("- Item one\n- Item two")
        assert len(blocks) == 2
        assert blocks[0]["type"] == "bulleted_list_item"
        assert blocks[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "Item one"
        assert blocks[1]["type"] == "bulleted_list_item"

    def test_bulleted_list_asterisk(self) -> None:
        blocks = _markdown_to_blocks("* Star item")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "bulleted_list_item"

    def test_numbered_list(self) -> None:
        blocks = _markdown_to_blocks("1. First\n2. Second")
        assert len(blocks) == 2
        assert blocks[0]["type"] == "numbered_list_item"
        assert blocks[0]["numbered_list_item"]["rich_text"][0]["text"]["content"] == "First"

    def test_todo_unchecked(self) -> None:
        blocks = _markdown_to_blocks("- [ ] Buy milk")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "to_do"
        assert blocks[0]["to_do"]["checked"] is False
        assert blocks[0]["to_do"]["rich_text"][0]["text"]["content"] == "Buy milk"

    def test_todo_checked(self) -> None:
        blocks = _markdown_to_blocks("- [x] Done task")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "to_do"
        assert blocks[0]["to_do"]["checked"] is True

    def test_todo_checked_uppercase(self) -> None:
        blocks = _markdown_to_blocks("- [X] Also done")
        assert len(blocks) == 1
        assert blocks[0]["to_do"]["checked"] is True

    def test_blockquote(self) -> None:
        blocks = _markdown_to_blocks("> This is a quote")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "quote"
        assert blocks[0]["quote"]["rich_text"][0]["text"]["content"] == "This is a quote"

    def test_divider_dashes(self) -> None:
        blocks = _markdown_to_blocks("---")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "divider"

    def test_divider_underscores(self) -> None:
        blocks = _markdown_to_blocks("___")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "divider"

    def test_divider_asterisks(self) -> None:
        blocks = _markdown_to_blocks("***")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "divider"

    def test_code_block(self) -> None:
        md = "```python\nprint('hello')\n```"
        blocks = _markdown_to_blocks(md)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "code"
        assert blocks[0]["code"]["language"] == "python"
        assert blocks[0]["code"]["rich_text"][0]["text"]["content"] == "print('hello')"

    def test_code_block_no_language(self) -> None:
        md = "```\nsome code\n```"
        blocks = _markdown_to_blocks(md)
        assert len(blocks) == 1
        assert blocks[0]["code"]["language"] == "plain text"

    def test_code_block_multiline(self) -> None:
        md = "```js\nconst x = 1;\nconst y = 2;\n```"
        blocks = _markdown_to_blocks(md)
        assert blocks[0]["code"]["rich_text"][0]["text"]["content"] == "const x = 1;\nconst y = 2;"

    def test_mixed_content(self) -> None:
        md = "# Title\n\nSome text\n\n- Item 1\n- Item 2\n\n> A quote\n\n---\n\n1. Numbered"
        blocks = _markdown_to_blocks(md)
        types = [b["type"] for b in blocks]
        assert types == [
            "heading_1",
            "paragraph",
            "bulleted_list_item",
            "bulleted_list_item",
            "quote",
            "divider",
            "numbered_list_item",
        ]

    def test_skips_blank_lines(self) -> None:
        blocks = _markdown_to_blocks("\n\n\nHello\n\n\n")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "paragraph"

    def test_consecutive_paragraph_lines_merged(self) -> None:
        blocks = _markdown_to_blocks("Line one\nLine two\nLine three")
        assert len(blocks) == 1
        assert "Line one\nLine two\nLine three" in blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]

    def test_paragraph_stops_at_heading(self) -> None:
        blocks = _markdown_to_blocks("Text\n# Heading")
        assert len(blocks) == 2
        assert blocks[0]["type"] == "paragraph"
        assert blocks[1]["type"] == "heading_1"


# ---------------------------------------------------------------------------
# NotionCreatePageParams validation
# ---------------------------------------------------------------------------


class TestNotionCreatePageParams:
    def test_database_id_only(self) -> None:
        params = NotionCreatePageParams(
            database_id="db-123", properties={"Name": "Test"}
        )
        assert params.database_id == "db-123"
        assert params.page_id is None

    def test_page_id_only(self) -> None:
        params = NotionCreatePageParams(
            page_id="page-123", properties={"title": "Test"}
        )
        assert params.page_id == "page-123"
        assert params.database_id is None

    def test_both_raises(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            NotionCreatePageParams(
                database_id="db-123", page_id="page-123", properties={"Name": "Test"}
            )

    def test_neither_raises(self) -> None:
        with pytest.raises(ValueError, match="required"):
            NotionCreatePageParams(properties={"Name": "Test"})


# ---------------------------------------------------------------------------
# notion_create_page — child page under page
# ---------------------------------------------------------------------------


class TestNotionCreateChildPage:
    async def test_child_page_under_page(self) -> None:
        page = _make_page()
        client = _mock_client()
        client.pages.create.return_value = page

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_create_page(
                page_id="parent-page-id",
                properties={"title": "Child Page"},
            )

        assert result.success
        create_kwargs = client.pages.create.call_args.kwargs
        assert create_kwargs["parent"] == {"page_id": "parent-page-id"}
        # Should have formatted the title property
        assert "title" in create_kwargs["properties"]
        title_rt = create_kwargs["properties"]["title"]["title"]
        assert title_rt[0]["text"]["content"] == "Child Page"

    async def test_child_page_with_name_key(self) -> None:
        page = _make_page()
        client = _mock_client()
        client.pages.create.return_value = page

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_create_page(
                page_id="parent-page-id",
                properties={"Name": "Named Child"},
            )

        assert result.success
        create_kwargs = client.pages.create.call_args.kwargs
        title_rt = create_kwargs["properties"]["title"]["title"]
        assert title_rt[0]["text"]["content"] == "Named Child"

    async def test_child_page_missing_title(self) -> None:
        with patch("src.tools.notion_tools._get_client", return_value=_mock_client()):
            result = await notion_create_page(
                page_id="parent-page-id",
                properties={"Status": "Active"},
            )

        assert not result.success
        assert "title" in result.error.lower()

    async def test_child_page_with_content(self) -> None:
        page = _make_page()
        client = _mock_client()
        client.pages.create.return_value = page

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_create_page(
                page_id="parent-page-id",
                properties={"title": "Child"},
                content="# Heading\n\nBody text",
            )

        assert result.success
        create_kwargs = client.pages.create.call_args.kwargs
        assert "children" in create_kwargs
        assert create_kwargs["children"][0]["type"] == "heading_1"


# ---------------------------------------------------------------------------
# _build_schema_payload
# ---------------------------------------------------------------------------


class TestBuildSchemaPayload:
    def test_simple_types(self) -> None:
        schema = _build_schema_payload({
            "Name": "title",
            "Notes": "rich_text",
            "Count": "number",
            "Due": "date",
        })
        assert schema["Name"] == {"title": {}}
        assert schema["Notes"] == {"rich_text": {}}
        assert schema["Count"] == {"number": {}}
        assert schema["Due"] == {"date": {}}

    def test_select_with_options(self) -> None:
        schema = _build_schema_payload({
            "Status": {"select": ["Todo", "Done"]},
        })
        assert schema["Status"] == {
            "select": {"options": [{"name": "Todo"}, {"name": "Done"}]},
        }

    def test_multi_select_with_options(self) -> None:
        schema = _build_schema_payload({
            "Tags": {"multi_select": ["Red", "Blue"]},
        })
        assert schema["Tags"] == {
            "multi_select": {"options": [{"name": "Red"}, {"name": "Blue"}]},
        }

    def test_status_with_options(self) -> None:
        schema = _build_schema_payload({
            "Status": {"status": ["Not Started", "In Progress", "Done"]},
        })
        assert schema["Status"]["status"]["options"][0]["name"] == "Not Started"

    def test_empty_type_dict(self) -> None:
        schema = _build_schema_payload({"Check": {"checkbox": {}}})
        assert schema["Check"] == {"checkbox": {}}

    def test_fallback_to_rich_text(self) -> None:
        schema = _build_schema_payload({"Weird": 12345})
        assert schema["Weird"] == {"rich_text": {}}


# ---------------------------------------------------------------------------
# notion_create_database
# ---------------------------------------------------------------------------


class TestNotionCreateDatabase:
    async def test_basic_create(self) -> None:
        client = _mock_client()
        client.request.return_value = {
            "id": "new-db-id",
            "title": [{"plain_text": "My DB"}],
            "url": "https://notion.so/new-db-id",
            "properties": {
                "Name": {"type": "title"},
                "Status": {"type": "select"},
            },
        }

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_create_database(
                page_id="parent-page",
                title="My DB",
                properties={"Name": "title", "Status": {"select": ["Todo", "Done"]}},
            )

        assert result.success
        assert result.data["id"] == "new-db-id"
        assert result.data["title"] == "My DB"

        # Verify API call
        call_kwargs = client.request.call_args.kwargs
        assert call_kwargs["path"] == "databases"
        assert call_kwargs["method"] == "POST"
        body = call_kwargs["body"]
        assert body["parent"] == {"page_id": "parent-page"}
        assert body["is_inline"] is True

    async def test_auto_adds_title_property(self) -> None:
        client = _mock_client()
        client.request.return_value = {
            "id": "db-id",
            "title": [{"plain_text": "DB"}],
            "url": "",
            "properties": {"Name": {"type": "title"}, "Count": {"type": "number"}},
        }

        with patch("src.tools.notion_tools._get_client", return_value=client):
            # No title property in schema — should auto-add "Name"
            await notion_create_database(
                page_id="parent",
                title="DB",
                properties={"Count": "number"},
            )

        body = client.request.call_args.kwargs["body"]
        assert "Name" in body["properties"]
        assert "title" in body["properties"]["Name"]

    async def test_does_not_duplicate_title(self) -> None:
        client = _mock_client()
        client.request.return_value = {
            "id": "db-id",
            "title": [{"plain_text": "DB"}],
            "url": "",
            "properties": {"Task": {"type": "title"}},
        }

        with patch("src.tools.notion_tools._get_client", return_value=client):
            await notion_create_database(
                page_id="parent",
                title="DB",
                properties={"Task": "title"},
            )

        body = client.request.call_args.kwargs["body"]
        # Should NOT have added an extra "Name" since "Task" is already title
        assert "Name" not in body["properties"]
        assert "Task" in body["properties"]

    async def test_full_page_database(self) -> None:
        client = _mock_client()
        client.request.return_value = {
            "id": "db-id",
            "title": [{"plain_text": "DB"}],
            "url": "",
            "properties": {},
        }

        with patch("src.tools.notion_tools._get_client", return_value=client):
            await notion_create_database(
                page_id="parent",
                title="DB",
                properties={"Name": "title"},
                is_inline=False,
            )

        body = client.request.call_args.kwargs["body"]
        assert body["is_inline"] is False

    async def test_api_error(self) -> None:
        exc = Exception("error")
        exc.message = "Cannot create"  # type: ignore[attr-defined]
        client = _mock_client()
        client.request.side_effect = exc

        with patch("src.tools.notion_tools._get_client", return_value=client):
            result = await notion_create_database(
                page_id="parent",
                title="DB",
                properties={"Name": "title"},
            )

        assert not result.success

    async def test_missing_config(self) -> None:
        with patch("src.tools.notion_tools._get_client", side_effect=ValueError("no key")):
            result = await notion_create_database(
                page_id="parent",
                title="DB",
                properties={"Name": "title"},
            )
        assert not result.success
