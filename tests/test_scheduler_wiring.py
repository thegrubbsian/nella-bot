"""Tests for scheduler wiring in bot app."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scheduler.store import TaskStore


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset singletons before and after each test."""
    from src.notifications.router import NotificationRouter
    from src.tools.scheduler_tools import init_scheduler_tools

    TaskStore._reset()
    NotificationRouter._reset()
    init_scheduler_tools(None)
    yield
    TaskStore._reset()
    NotificationRouter._reset()
    init_scheduler_tools(None)


def test_init_scheduler_creates_engine() -> None:
    """_init_scheduler should return a SchedulerEngine with store and executor."""
    from src.notifications.router import NotificationRouter

    # Set up a router with a fake channel so set_default_channel works
    router = NotificationRouter.get()
    fake_channel = MagicMock()
    fake_channel.name = "telegram"
    router.register_channel(fake_channel)
    router.set_default_channel("telegram")

    with patch("src.bot.app.settings") as mock_settings:
        mock_settings.get_allowed_user_ids.return_value = {12345}
        mock_settings.scheduler_timezone = "America/Chicago"
        mock_settings.database_path = "data/nella.db"
        mock_settings.default_notification_channel = "telegram"

        from src.bot.app import _init_scheduler

        engine = _init_scheduler()

    assert engine is not None
    assert engine._store is not None
    assert engine._executor is not None
    assert engine._executor._owner_user_id == "12345"


def test_init_scheduler_tools_wired() -> None:
    """After _init_scheduler, the scheduler tools should have access to the engine."""
    from src.notifications.router import NotificationRouter

    router = NotificationRouter.get()
    fake_channel = MagicMock()
    fake_channel.name = "telegram"
    router.register_channel(fake_channel)
    router.set_default_channel("telegram")

    with patch("src.bot.app.settings") as mock_settings:
        mock_settings.get_allowed_user_ids.return_value = {12345}
        mock_settings.scheduler_timezone = "America/Chicago"
        mock_settings.database_path = "data/nella.db"
        mock_settings.default_notification_channel = "telegram"

        from src.bot.app import _init_scheduler

        engine = _init_scheduler()

    from src.tools.scheduler_tools import _engine

    assert _engine is engine


async def test_post_init_starts_engine() -> None:
    """_post_init should create and start the scheduler engine."""
    from src.notifications.router import NotificationRouter

    router = NotificationRouter.get()
    fake_channel = MagicMock()
    fake_channel.name = "telegram"
    router.register_channel(fake_channel)
    router.set_default_channel("telegram")

    mock_app = AsyncMock()

    with patch("src.bot.app.settings") as mock_settings:
        mock_settings.get_allowed_user_ids.return_value = {12345}
        mock_settings.scheduler_timezone = "America/Chicago"
        mock_settings.database_path = "data/nella.db"
        mock_settings.default_notification_channel = "telegram"

        import src.bot.app as app_module

        await app_module._post_init(mock_app)

    assert app_module._scheduler_engine is not None
    assert app_module._scheduler_engine.running is True

    # Clean up
    await app_module._scheduler_engine.stop()
    app_module._scheduler_engine = None


async def test_post_shutdown_stops_engine() -> None:
    """_post_shutdown should stop the scheduler engine."""
    from src.notifications.router import NotificationRouter

    router = NotificationRouter.get()
    fake_channel = MagicMock()
    fake_channel.name = "telegram"
    router.register_channel(fake_channel)
    router.set_default_channel("telegram")

    mock_app = AsyncMock()

    with patch("src.bot.app.settings") as mock_settings:
        mock_settings.get_allowed_user_ids.return_value = {12345}
        mock_settings.scheduler_timezone = "America/Chicago"
        mock_settings.database_path = "data/nella.db"
        mock_settings.default_notification_channel = "telegram"

        import src.bot.app as app_module

        await app_module._post_init(mock_app)

    engine = app_module._scheduler_engine
    assert engine.running is True

    await app_module._post_shutdown(mock_app)
    assert engine.running is False

    # Clean up
    app_module._scheduler_engine = None


async def test_post_shutdown_noop_when_no_engine() -> None:
    """_post_shutdown should not raise when no engine exists."""
    import src.bot.app as app_module

    app_module._scheduler_engine = None
    await app_module._post_shutdown(AsyncMock())  # Should not raise


def test_scheduler_tools_registered() -> None:
    """The scheduler tools should be registered in the global registry."""
    import src.tools.scheduler_tools  # noqa: F401
    from src.tools.registry import registry

    assert registry.get("schedule_task") is not None
    assert registry.get("list_scheduled_tasks") is not None
    assert registry.get("cancel_scheduled_task") is not None


def test_schedule_task_requires_confirmation() -> None:
    """schedule_task should require confirmation."""
    from src.tools.registry import registry

    tool_def = registry.get("schedule_task")
    assert tool_def is not None
    assert tool_def.requires_confirmation is True


def test_cancel_task_requires_confirmation() -> None:
    """cancel_scheduled_task should require confirmation."""
    from src.tools.registry import registry

    tool_def = registry.get("cancel_scheduled_task")
    assert tool_def is not None
    assert tool_def.requires_confirmation is True


def test_list_tasks_no_confirmation() -> None:
    """list_scheduled_tasks should not require confirmation."""
    from src.tools.registry import registry

    tool_def = registry.get("list_scheduled_tasks")
    assert tool_def is not None
    assert tool_def.requires_confirmation is False
