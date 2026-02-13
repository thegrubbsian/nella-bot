"""Tests for the browse_web tool."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from src.browser.agent import BrowseResult
from src.tools.browser_tools import BrowseWebParams, browse_web


class TestBrowseWebParams:
    def test_valid_params(self):
        params = BrowseWebParams(url="https://example.com", task="Read the page")
        assert params.url == "https://example.com"
        assert params.task == "Read the page"

    def test_missing_url_raises(self):
        with pytest.raises(ValidationError):
            BrowseWebParams(task="Read the page")

    def test_missing_task_raises(self):
        with pytest.raises(ValidationError):
            BrowseWebParams(url="https://example.com")


class TestBrowseWebTool:
    async def test_success_path(self):
        """Successful browse returns summary data."""
        mock_result = BrowseResult(
            success=True,
            summary="The page says Hello World.",
            steps_taken=2,
            url="https://example.com",
        )

        mock_agent = AsyncMock()
        mock_agent.run.return_value = mock_result

        mock_page = AsyncMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.new_page.return_value = mock_page

        with (
            patch("src.tools.browser_tools.BrowserSession", return_value=mock_session),
            patch("src.tools.browser_tools.BrowserAgent", return_value=mock_agent),
        ):
            result = await browse_web(url="https://example.com", task="Read the page")

        assert result.success
        assert result.data["summary"] == "The page says Hello World."
        assert result.data["steps_taken"] == 2

    async def test_error_path(self):
        """Failed browse returns error."""
        mock_result = BrowseResult(
            success=False,
            summary="Got stuck on a login page.",
            steps_taken=5,
            url="https://example.com/login",
            error="Max steps reached",
        )

        mock_agent = AsyncMock()
        mock_agent.run.return_value = mock_result

        mock_page = AsyncMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.new_page.return_value = mock_page

        with (
            patch("src.tools.browser_tools.BrowserSession", return_value=mock_session),
            patch("src.tools.browser_tools.BrowserAgent", return_value=mock_agent),
        ):
            result = await browse_web(url="https://example.com", task="Login and find data")

        assert not result.success
        assert "5 steps" in result.error
        assert "Max steps reached" in result.error

    async def test_unexpected_exception(self):
        """Unexpected exception returns generic error."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(side_effect=RuntimeError("Chromium not installed"))
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.tools.browser_tools.BrowserSession", return_value=mock_session):
            result = await browse_web(url="https://example.com", task="Read the page")

        assert not result.success
        assert "failed" in result.error.lower()
