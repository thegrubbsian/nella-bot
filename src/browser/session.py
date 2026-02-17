"""Browser session — async context manager wrapping Playwright lifecycle."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from playwright.async_api import async_playwright

if TYPE_CHECKING:
    from types import TracebackType

    from playwright.async_api import BrowserContext, Page

from src.config import settings

logger = logging.getLogger(__name__)

# Viewport that balances readability with fitting enough content
DEFAULT_VIEWPORT = {"width": 1280, "height": 720}

# Chromium launch args for headless VPS compatibility
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
]

# Only one persistent context can use a profile dir at a time
_profile_lock = asyncio.Lock()


class BrowserSession:
    """Manages a headless Chromium browser for a single browsing task.

    Uses a persistent browser profile so cookies and state survive across
    calls, and applies playwright-stealth evasions to reduce bot detection.

    Usage::

        async with BrowserSession() as session:
            page = await session.new_page()
            await page.goto("https://example.com")
    """

    def __init__(self, timeout_ms: int | None = None) -> None:
        self._timeout_ms = timeout_ms or settings.browser_timeout_ms
        self._playwright = None
        self._context: BrowserContext | None = None

    async def start(self) -> None:
        """Launch the browser with a persistent profile and stealth evasions."""
        profile_dir = settings.browser_profile_dir
        profile_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            args=CHROMIUM_ARGS,
            viewport=DEFAULT_VIEWPORT,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        self._context.set_default_timeout(self._timeout_ms)

        # Apply stealth evasions (init_scripts_only because we supply our own UA + args)
        try:
            from playwright_stealth import Stealth

            stealth = Stealth(init_scripts_only=True)
            await stealth.apply_stealth_async(self._context)
            logger.info("Stealth evasions applied")
        except Exception:
            logger.warning("Failed to apply stealth evasions — continuing without", exc_info=True)

        logger.info("Browser session started (timeout=%dms)", self._timeout_ms)

    async def stop(self) -> None:
        """Close everything."""
        if self._context:
            await self._context.close()
            self._context = None
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
        await _profile_lock.acquire()
        try:
            await self.start()
        except BaseException:
            _profile_lock.release()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            await self.stop()
        finally:
            _profile_lock.release()
