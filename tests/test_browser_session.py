"""Tests for BrowserSession lifecycle."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def _mock_playwright():
    """Mock the entire Playwright stack."""
    page = AsyncMock()
    context = AsyncMock()
    context.new_page.return_value = page
    context.set_default_timeout = MagicMock()

    browser = AsyncMock()
    browser.new_context.return_value = context

    pw = AsyncMock()
    pw.chromium.launch.return_value = browser

    pw_cm = AsyncMock()
    pw_cm.start.return_value = pw

    with patch("src.browser.session.async_playwright", return_value=pw_cm):
        yield {
            "playwright": pw,
            "pw_cm": pw_cm,
            "browser": browser,
            "context": context,
            "page": page,
        }


class TestBrowserSession:
    async def test_start_and_stop(self, _mock_playwright):
        from src.browser.session import BrowserSession

        session = BrowserSession(timeout_ms=5000)
        await session.start()

        # Browser was launched headless
        _mock_playwright["playwright"].chromium.launch.assert_called_once()
        call_kwargs = _mock_playwright["playwright"].chromium.launch.call_args
        assert call_kwargs.kwargs["headless"] is True

        # Context was created with viewport
        _mock_playwright["browser"].new_context.assert_called_once()

        # Timeout was set
        _mock_playwright["context"].set_default_timeout.assert_called_once_with(5000)

        # Stop cleans up
        await session.stop()
        _mock_playwright["context"].close.assert_called_once()
        _mock_playwright["browser"].close.assert_called_once()
        _mock_playwright["playwright"].stop.assert_called_once()

    async def test_context_manager(self, _mock_playwright):
        from src.browser.session import BrowserSession

        async with BrowserSession() as session:
            page = await session.new_page()
            assert page is _mock_playwright["page"]

        # Cleanup happened
        _mock_playwright["context"].close.assert_called_once()
        _mock_playwright["browser"].close.assert_called_once()

    async def test_new_page_without_start_raises(self):
        from src.browser.session import BrowserSession

        session = BrowserSession()
        with pytest.raises(RuntimeError, match="not started"):
            await session.new_page()

    async def test_stop_is_idempotent(self, _mock_playwright):
        from src.browser.session import BrowserSession

        session = BrowserSession()
        await session.start()
        await session.stop()
        await session.stop()  # Should not raise

        # close called only once
        assert _mock_playwright["context"].close.call_count == 1

    async def test_default_timeout_from_settings(self, _mock_playwright, monkeypatch):
        monkeypatch.setattr("src.browser.session.settings.browser_timeout_ms", 15000)

        from src.browser.session import BrowserSession

        session = BrowserSession()
        await session.start()
        _mock_playwright["context"].set_default_timeout.assert_called_once_with(15000)
        await session.stop()
