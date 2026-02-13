"""Browser session — async context manager wrapping Playwright lifecycle."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from playwright.async_api import async_playwright

if TYPE_CHECKING:
    from types import TracebackType

    from playwright.async_api import Browser, BrowserContext, Page

from src.config import settings

logger = logging.getLogger(__name__)

# Viewport that balances readability with fitting enough content
DEFAULT_VIEWPORT = {"width": 1280, "height": 720}

# Chromium launch args for headless VPS compatibility
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
]


class BrowserSession:
    """Manages a headless Chromium browser for a single browsing task.

    Usage::

        async with BrowserSession() as session:
            page = await session.new_page()
            await page.goto("https://example.com")
    """

    def __init__(self, timeout_ms: int | None = None) -> None:
        self._timeout_ms = timeout_ms or settings.browser_timeout_ms
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def start(self) -> None:
        """Launch the browser."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=CHROMIUM_ARGS,
        )
        self._context = await self._browser.new_context(
            viewport=DEFAULT_VIEWPORT,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._context.set_default_timeout(self._timeout_ms)
        logger.info("Browser session started (timeout=%dms)", self._timeout_ms)

    async def stop(self) -> None:
        """Close everything."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Browser session stopped")

    async def new_page(self) -> Page:
        """Create a new page in the browser context."""
        if self._context is None:
            msg = "Browser session not started — call start() or use as async context manager"
            raise RuntimeError(msg)
        return await self._context.new_page()

    async def __aenter__(self) -> BrowserSession:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.stop()
