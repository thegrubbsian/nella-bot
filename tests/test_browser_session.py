"""Tests for BrowserSession lifecycle."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def _mock_playwright(tmp_path, monkeypatch):
    """Mock the entire Playwright stack (persistent context + stealth)."""
    monkeypatch.setattr("src.browser.session.settings.browser_profile_dir", tmp_path / "profile")

    page = AsyncMock()
    context = AsyncMock()
    context.new_page.return_value = page
    context.set_default_timeout = MagicMock()

    pw = AsyncMock()
    pw.chromium.launch_persistent_context.return_value = context

    pw_cm = AsyncMock()
    pw_cm.start.return_value = pw

    stealth_instance = MagicMock()
    stealth_instance.apply_stealth_async = AsyncMock()
    stealth_cls = MagicMock(return_value=stealth_instance)

    with (
        patch("src.browser.session.async_playwright", return_value=pw_cm),
        patch("src.browser.session.Stealth", stealth_cls, create=True),
        patch.dict("sys.modules", {"playwright_stealth": MagicMock(Stealth=stealth_cls)}),
    ):
        yield {
            "playwright": pw,
            "pw_cm": pw_cm,
            "context": context,
            "page": page,
            "stealth_cls": stealth_cls,
            "stealth_instance": stealth_instance,
        }


class TestBrowserSession:
    async def test_start_and_stop(self, _mock_playwright, tmp_path):
        from src.browser.session import BrowserSession

        session = BrowserSession(timeout_ms=5000)
        await session.start()

        # Persistent context was launched
        _mock_playwright["playwright"].chromium.launch_persistent_context.assert_called_once()
        call_kwargs = _mock_playwright["playwright"].chromium.launch_persistent_context.call_args
        assert call_kwargs.kwargs["headless"] is True
        assert call_kwargs.kwargs["user_data_dir"] == str(tmp_path / "profile")

        # Timeout was set
        _mock_playwright["context"].set_default_timeout.assert_called_once_with(5000)

        # Stealth was applied
        _mock_playwright["stealth_cls"].assert_called_once_with(init_scripts_only=True)
        _mock_playwright["stealth_instance"].apply_stealth_async.assert_called_once_with(
            _mock_playwright["context"]
        )

        # Stop cleans up (no browser.close — persistent context only)
        await session.stop()
        _mock_playwright["context"].close.assert_called_once()
        _mock_playwright["playwright"].stop.assert_called_once()

    async def test_context_manager(self, _mock_playwright):
        from src.browser.session import BrowserSession

        async with BrowserSession() as session:
            page = await session.new_page()
            assert page is _mock_playwright["page"]

        # Cleanup happened
        _mock_playwright["context"].close.assert_called_once()

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

    async def test_profile_dir_created(self, _mock_playwright, tmp_path):
        from src.browser.session import BrowserSession

        profile_dir = tmp_path / "profile"
        assert not profile_dir.exists()

        session = BrowserSession()
        await session.start()
        assert profile_dir.is_dir()
        await session.stop()

    async def test_stealth_failure_does_not_crash(self, tmp_path, monkeypatch):
        """If stealth import/apply fails, the session still starts."""
        monkeypatch.setattr(
            "src.browser.session.settings.browser_profile_dir", tmp_path / "profile"
        )

        context = AsyncMock()
        context.set_default_timeout = MagicMock()
        context.new_page.return_value = AsyncMock()

        pw = AsyncMock()
        pw.chromium.launch_persistent_context.return_value = context

        pw_cm = AsyncMock()
        pw_cm.start.return_value = pw

        with (
            patch("src.browser.session.async_playwright", return_value=pw_cm),
            patch.dict("sys.modules", {"playwright_stealth": None}),
        ):
            from src.browser.session import BrowserSession

            session = BrowserSession()
            await session.start()

            # Session works despite stealth failure
            page = await session.new_page()
            assert page is not None
            await session.stop()

    async def test_updated_user_agent(self, _mock_playwright):
        from src.browser.session import BrowserSession

        session = BrowserSession()
        await session.start()

        call_kwargs = _mock_playwright["playwright"].chromium.launch_persistent_context.call_args
        assert "Chrome/131" in call_kwargs.kwargs["user_agent"]
        await session.stop()

    async def test_context_manager_releases_lock_on_start_failure(self, tmp_path, monkeypatch):
        """If start() fails, the profile lock is released."""
        monkeypatch.setattr(
            "src.browser.session.settings.browser_profile_dir", tmp_path / "profile"
        )

        pw_cm = AsyncMock()
        pw_cm.start.side_effect = RuntimeError("launch failed")

        with patch("src.browser.session.async_playwright", return_value=pw_cm):
            from src.browser.session import BrowserSession, _profile_lock

            with pytest.raises(RuntimeError, match="launch failed"):
                async with BrowserSession():
                    pass  # pragma: no cover

            # Lock was released despite failure
            assert not _profile_lock.locked()
