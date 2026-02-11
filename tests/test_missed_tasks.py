"""Tests for missed scheduled task recovery."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from src.scheduler.engine import SchedulerEngine
from src.scheduler.executor import TaskExecutor
from src.scheduler.missed import (
    _pending_missed,
    check_and_notify_missed_tasks,
    handle_missed_task_callback,
    init_missed_task_recovery,
)
from src.scheduler.models import ScheduledTask, make_task_id
from src.scheduler.store import TaskStore

try:
    import zoneinfo
except ImportError:  # pragma: no cover
    from backports import zoneinfo  # type: ignore[no-redef]

TZ = "America/Chicago"


@pytest.fixture(autouse=True)
def _no_turso(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests use local file, not remote Turso."""
    monkeypatch.setattr("src.config.settings.turso_database_url", "")


@pytest.fixture(autouse=True)
def _clear_pending() -> None:
    """Clear pending missed dict before each test."""
    _pending_missed.clear()


@pytest.fixture
async def store(tmp_path: Path) -> TaskStore:
    return TaskStore(db_path=tmp_path / "test.db")


@pytest.fixture
def executor(store: TaskStore) -> TaskExecutor:
    return TaskExecutor(
        router=AsyncMock(),
        generate_response=AsyncMock(return_value="ok"),
        store=store,
        owner_user_id="12345",
    )


@pytest.fixture
async def engine(store: TaskStore, executor: TaskExecutor) -> SchedulerEngine:
    eng = SchedulerEngine(store=store, executor=executor, timezone=TZ)
    await eng.start()
    init_missed_task_recovery(eng, executor, "12345")
    yield eng
    await eng.stop()


def _make_task(
    *,
    task_type: str = "one_off",
    run_at: str | None = None,
    cron: str | None = None,
    last_run_at: str | None = None,
    active: bool = True,
) -> ScheduledTask:
    """Helper to create a ScheduledTask for testing."""
    schedule: dict = {}
    if task_type == "one_off":
        schedule["run_at"] = run_at or "2020-01-01T00:00:00-06:00"
    else:
        schedule["cron"] = cron or "0 8 * * *"

    return ScheduledTask(
        id=make_task_id(),
        name="Test task",
        task_type=task_type,
        schedule=schedule,
        action={"type": "simple_message", "message": "hello"},
        active=active,
        last_run_at=last_run_at,
    )


# -- Detection tests -----------------------------------------------------------


async def test_detects_missed_one_off_task(engine: SchedulerEngine, store: TaskStore) -> None:
    """A past one-off task with no last_run_at is detected as missed."""
    past = (datetime.now(zoneinfo.ZoneInfo(TZ)) - timedelta(hours=1)).isoformat()
    task = _make_task(run_at=past)
    await store.add_task(task)

    with patch("src.scheduler.missed.NotificationRouter") as mock_router_cls:
        mock_router = MagicMock()
        mock_router.send_rich = AsyncMock(return_value=True)
        mock_router_cls.get.return_value = mock_router

        count = await check_and_notify_missed_tasks()

    assert count == 1
    mock_router.send_rich.assert_called_once()
    call_kwargs = mock_router.send_rich.call_args
    assert "Missed scheduled task" in call_kwargs.args[1]
    assert len(_pending_missed) == 1


async def test_ignores_future_one_off_task(engine: SchedulerEngine, store: TaskStore) -> None:
    """A future one-off task should not be detected as missed."""
    future = (datetime.now(zoneinfo.ZoneInfo(TZ)) + timedelta(hours=1)).isoformat()
    task = _make_task(run_at=future)
    await store.add_task(task)

    with patch("src.scheduler.missed.NotificationRouter") as mock_router_cls:
        mock_router = MagicMock()
        mock_router.send_rich = AsyncMock(return_value=True)
        mock_router_cls.get.return_value = mock_router

        count = await check_and_notify_missed_tasks()

    assert count == 0
    mock_router.send_rich.assert_not_called()


async def test_ignores_already_executed_task(engine: SchedulerEngine, store: TaskStore) -> None:
    """A one-off task that already ran (has last_run_at) should be ignored."""
    past = (datetime.now(zoneinfo.ZoneInfo(TZ)) - timedelta(hours=1)).isoformat()
    task = _make_task(run_at=past, last_run_at=past)
    await store.add_task(task)

    with patch("src.scheduler.missed.NotificationRouter") as mock_router_cls:
        mock_router = MagicMock()
        mock_router.send_rich = AsyncMock(return_value=True)
        mock_router_cls.get.return_value = mock_router

        count = await check_and_notify_missed_tasks()

    assert count == 0


async def test_ignores_recurring_task(engine: SchedulerEngine, store: TaskStore) -> None:
    """Recurring tasks should never be flagged as missed."""
    task = _make_task(task_type="recurring", cron="0 8 * * *")
    await store.add_task(task)

    with patch("src.scheduler.missed.NotificationRouter") as mock_router_cls:
        mock_router = MagicMock()
        mock_router.send_rich = AsyncMock(return_value=True)
        mock_router_cls.get.return_value = mock_router

        count = await check_and_notify_missed_tasks()

    assert count == 0


async def test_multiple_missed_tasks_send_multiple_messages(
    engine: SchedulerEngine, store: TaskStore
) -> None:
    """Each missed task sends its own notification."""
    past = (datetime.now(zoneinfo.ZoneInfo(TZ)) - timedelta(hours=1)).isoformat()
    task1 = _make_task(run_at=past)
    task1.name = "Task A"
    task2 = _make_task(run_at=past)
    task2.name = "Task B"
    await store.add_task(task1)
    await store.add_task(task2)

    with patch("src.scheduler.missed.NotificationRouter") as mock_router_cls:
        mock_router = MagicMock()
        mock_router.send_rich = AsyncMock(return_value=True)
        mock_router_cls.get.return_value = mock_router

        count = await check_and_notify_missed_tasks()

    assert count == 2
    assert mock_router.send_rich.call_count == 2
    assert len(_pending_missed) == 2


# -- Callback handling tests ---------------------------------------------------


async def test_callback_run_executes_and_deactivates(
    engine: SchedulerEngine, store: TaskStore, executor: TaskExecutor
) -> None:
    """Pressing 'Run Now' should execute the task and deactivate it."""
    past = (datetime.now(zoneinfo.ZoneInfo(TZ)) - timedelta(hours=1)).isoformat()
    task = _make_task(run_at=past)
    await store.add_task(task)

    key = "abc12345"
    _pending_missed[key] = task.id

    query = AsyncMock()
    query.message = MagicMock()
    query.message.text = "Missed scheduled task: Test task"

    await handle_missed_task_callback(query, conf_key=key, action="run")

    # Task should be deactivated
    stored = await store.get_task(task.id)
    assert stored is not None
    assert not stored.active

    # Key should be removed
    assert key not in _pending_missed

    query.answer.assert_called_with("Executed")
    query.edit_message_text.assert_called_once()
    assert "Executed" in query.edit_message_text.call_args.kwargs["text"]


async def test_callback_delete_deactivates(
    engine: SchedulerEngine, store: TaskStore
) -> None:
    """Pressing 'Delete' should deactivate the task without executing."""
    past = (datetime.now(zoneinfo.ZoneInfo(TZ)) - timedelta(hours=1)).isoformat()
    task = _make_task(run_at=past)
    await store.add_task(task)

    key = "def67890"
    _pending_missed[key] = task.id

    query = AsyncMock()
    query.message = MagicMock()
    query.message.text = "Missed scheduled task: Test task"

    await handle_missed_task_callback(query, conf_key=key, action="del")

    stored = await store.get_task(task.id)
    assert stored is not None
    assert not stored.active

    assert key not in _pending_missed
    query.answer.assert_called_with("Deleted")


async def test_callback_expired_key(engine: SchedulerEngine) -> None:
    """An unknown key (e.g. after restart) should respond with 'expired'."""
    query = AsyncMock()
    query.message = MagicMock()
    query.message.text = "Old missed task message"

    await handle_missed_task_callback(query, conf_key="expired1", action="run")

    query.answer.assert_called_with("This notification has expired.")
    query.edit_message_text.assert_called_once()
    assert "(expired)" in query.edit_message_text.call_args.kwargs["text"]


# -- Handler routing test ------------------------------------------------------


async def test_handler_routes_mst_prefix() -> None:
    """handle_callback_query should route mst: callbacks to handle_missed_task_callback."""
    from unittest.mock import patch as mock_patch

    from src.bot.handlers import handle_callback_query

    update = MagicMock()
    query = AsyncMock()
    query.data = "mst:abcd1234:run"
    update.callback_query = query
    context = MagicMock()

    with mock_patch(
        "src.scheduler.missed.handle_missed_task_callback", new_callable=AsyncMock
    ) as mock_handler:
        await handle_callback_query(update, context)

        mock_handler.assert_called_once_with(query, conf_key="abcd1234", action="run")


async def test_handler_rejects_invalid_mst_action() -> None:
    """mst: callback with invalid action should answer with error."""
    from src.bot.handlers import handle_callback_query

    update = MagicMock()
    query = AsyncMock()
    query.data = "mst:abcd1234:bad"
    update.callback_query = query
    context = MagicMock()

    await handle_callback_query(update, context)

    query.answer.assert_called_with("Invalid callback data.")
