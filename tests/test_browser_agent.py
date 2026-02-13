"""Tests for BrowserAgent — the autonomous navigation loop."""

from unittest.mock import AsyncMock, patch

import pytest

from src.browser.agent import BrowserAgent, BrowseResult


@pytest.fixture
def mock_page():
    """Create a mock Playwright page."""
    page = AsyncMock()
    page.url = "https://example.com"
    page.goto = AsyncMock()
    page.evaluate = AsyncMock(return_value=[])
    page.screenshot = AsyncMock(return_value=b"\x89PNG fake screenshot data")
    page.mouse = AsyncMock()
    page.keyboard = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.select_option = AsyncMock()
    return page


@pytest.fixture
def _mock_complete_text():
    """Patch complete_text used by BrowserAgent."""
    with patch("src.browser.agent.complete_text", new_callable=AsyncMock) as mock:
        yield mock


class TestBrowserAgent:
    async def test_done_on_first_step(self, mock_page, _mock_complete_text):
        """Agent returns done immediately."""
        _mock_complete_text.return_value = '{"action": "done", "summary": "Page says hello world."}'

        agent = BrowserAgent(mock_page, "Read the page content", max_steps=5)
        result = await agent.run("https://example.com")

        assert isinstance(result, BrowseResult)
        assert result.success is True
        assert result.summary == "Page says hello world."
        assert result.steps_taken == 1
        mock_page.goto.assert_called_once()

    async def test_click_then_done(self, mock_page, _mock_complete_text):
        """Agent clicks an element, then completes."""
        mock_page.evaluate.return_value = [
            {
                "index": 0, "tag": "a", "type": "", "text": "Click me",
                "href": "/next", "name": "", "x": 100, "y": 200,
            },
        ]

        _mock_complete_text.side_effect = [
            '{"action": "click", "index": 0}',
            '{"action": "done", "summary": "Clicked the link and found the info."}',
        ]

        agent = BrowserAgent(mock_page, "Click the link", max_steps=5)
        result = await agent.run("https://example.com")

        assert result.success is True
        assert result.steps_taken == 2
        mock_page.mouse.click.assert_called_once_with(100, 200)

    async def test_fill_action(self, mock_page, _mock_complete_text):
        """Agent fills a text input."""
        mock_page.evaluate.return_value = [
            {
                "index": 0, "tag": "input", "type": "text", "text": "",
                "href": "", "name": "search", "x": 300, "y": 100,
            },
        ]

        _mock_complete_text.side_effect = [
            '{"action": "fill", "index": 0, "value": "hello world"}',
            '{"action": "done", "summary": "Filled the search box."}',
        ]

        agent = BrowserAgent(mock_page, "Search for hello world", max_steps=5)
        result = await agent.run("https://example.com")

        assert result.success is True
        mock_page.mouse.click.assert_called_once_with(300, 100)
        mock_page.keyboard.type.assert_called_once_with("hello world", delay=30)

    async def test_scroll_action(self, mock_page, _mock_complete_text):
        """Agent scrolls the page."""
        _mock_complete_text.side_effect = [
            '{"action": "scroll", "direction": "down"}',
            '{"action": "done", "summary": "Found it after scrolling."}',
        ]

        agent = BrowserAgent(mock_page, "Find the footer", max_steps=5)
        result = await agent.run("https://example.com")

        assert result.success is True
        mock_page.mouse.wheel.assert_called_once_with(0, 500)

    async def test_navigate_action(self, mock_page, _mock_complete_text):
        """Agent navigates to a new URL."""
        _mock_complete_text.side_effect = [
            '{"action": "navigate", "url": "https://other.example.com"}',
            '{"action": "done", "summary": "Found the page."}',
        ]

        agent = BrowserAgent(mock_page, "Go to other site", max_steps=5)
        result = await agent.run("https://example.com")

        assert result.success is True
        assert mock_page.goto.call_count == 2

    async def test_wait_action(self, mock_page, _mock_complete_text):
        """Agent waits for content to load."""
        _mock_complete_text.side_effect = [
            '{"action": "wait", "seconds": 3}',
            '{"action": "done", "summary": "Content loaded."}',
        ]

        agent = BrowserAgent(mock_page, "Wait for content", max_steps=5)
        result = await agent.run("https://example.com")

        assert result.success is True
        mock_page.wait_for_timeout.assert_called_once_with(3000)

    async def test_wait_capped_at_5_seconds(self, mock_page, _mock_complete_text):
        """Wait action is capped at 5 seconds."""
        _mock_complete_text.side_effect = [
            '{"action": "wait", "seconds": 60}',
            '{"action": "done", "summary": "Done."}',
        ]

        agent = BrowserAgent(mock_page, "Wait", max_steps=5)
        await agent.run("https://example.com")

        mock_page.wait_for_timeout.assert_called_once_with(5000)

    async def test_max_steps_reached(self, mock_page, _mock_complete_text):
        """Agent stops after max steps."""
        _mock_complete_text.return_value = '{"action": "scroll", "direction": "down"}'

        agent = BrowserAgent(mock_page, "Find something", max_steps=3)
        result = await agent.run("https://example.com")

        assert result.success is False
        assert result.steps_taken == 3
        assert result.error == "Max steps reached"

    async def test_navigation_failure(self, mock_page, _mock_complete_text):
        """Agent handles page.goto failure gracefully."""
        mock_page.goto.side_effect = Exception("net::ERR_NAME_NOT_RESOLVED")

        agent = BrowserAgent(mock_page, "Read the page", max_steps=5)
        result = await agent.run("https://nonexistent.example.com")

        assert result.success is False
        assert "ERR_NAME_NOT_RESOLVED" in result.error

    async def test_select_action(self, mock_page, _mock_complete_text):
        """Agent selects a dropdown option."""
        mock_page.evaluate.return_value = [
            {
                "index": 0, "tag": "select", "type": "", "text": "Option A",
                "href": "", "name": "color", "x": 200, "y": 150,
            },
        ]

        _mock_complete_text.side_effect = [
            '{"action": "select", "index": 0, "value": "blue"}',
            '{"action": "done", "summary": "Selected blue."}',
        ]

        agent = BrowserAgent(mock_page, "Select blue", max_steps=5)
        result = await agent.run("https://example.com")

        assert result.success is True
        mock_page.select_option.assert_called_once_with('[name="color"]', "blue")


class TestParseAction:
    """Test the JSON parsing logic."""

    def test_clean_json(self):
        raw = '{"action": "click", "index": 3}'
        result = BrowserAgent._parse_action(raw)
        assert result == {"action": "click", "index": 3}

    def test_json_in_markdown_fences(self):
        raw = '```json\n{"action": "done", "summary": "Found it."}\n```'
        result = BrowserAgent._parse_action(raw)
        assert result == {"action": "done", "summary": "Found it."}

    def test_json_in_freeform_text(self):
        raw = (
            'I think the best action is: '
            '{"action": "scroll", "direction": "down"} '
            'because we need to see more.'
        )
        result = BrowserAgent._parse_action(raw)
        assert result == {"action": "scroll", "direction": "down"}

    def test_freeform_text_becomes_done(self):
        raw = "The page shows today's weather is sunny and 72 degrees."
        result = BrowserAgent._parse_action(raw)
        assert result["action"] == "done"
        assert "sunny" in result["summary"]

    def test_empty_string(self):
        result = BrowserAgent._parse_action("")
        assert result["action"] == "done"

    def test_json_without_action_key(self):
        raw = '{"foo": "bar"}'
        result = BrowserAgent._parse_action(raw)
        assert result["action"] == "done"


class TestFormatElements:
    def test_format_mixed_elements(self):
        elements = [
            {"index": 0, "tag": "a", "type": "", "text": "Home", "href": "/", "name": ""},
            {"index": 1, "tag": "input", "type": "text", "text": "", "href": "", "name": "q"},
        ]
        text = BrowserAgent._format_elements(elements)
        assert "[0] a" in text
        assert '"Home"' in text
        assert '[1] input type="text"' in text
        assert 'name="q"' in text

    def test_empty_list(self):
        text = BrowserAgent._format_elements([])
        assert "no interactive elements" in text


class TestResolveModel:
    def test_friendly_name(self):
        result = BrowserAgent._resolve_model("sonnet")
        assert "sonnet" in result

    def test_full_model_id(self):
        result = BrowserAgent._resolve_model("claude-sonnet-4-5-20250929")
        assert result == "claude-sonnet-4-5-20250929"

    def test_unknown_falls_back_to_sonnet(self):
        result = BrowserAgent._resolve_model("nonexistent-model")
        assert "sonnet" in result
