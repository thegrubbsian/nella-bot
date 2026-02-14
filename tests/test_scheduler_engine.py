"""Tests for SchedulerEngine — APScheduler lifecycle."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.scheduler.engine import SchedulerEngine
from src.scheduler.executor import TaskExecutor
from src.scheduler.models import ScheduledTask
from src.scheduler.store import TaskStore

pytestmark = pytest.mark.usefixtures("_no_turso")


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
def engine(store: TaskStore, executor: TaskExecutor) -> SchedulerEngine:
    return SchedulerEngine(store=store, executor=executor, timezone="America/Chicago")


def _make_task(
    task_id: str = "task1",
    task_type: str = "recurring",
    schedule: dict | None = None,
    **kwargs,
) -> ScheduledTask:
    defaults = {
        "name": "Test Task",
        "action": {"type": "simple_message", "message": "hi"},
        "created_at": "2025-01-01T00:00:00",
    }
    defaults.update(kwargs)
    return ScheduledTask(
        id=task_id,
        task_type=task_type,
        schedule=schedule or {"cron": "0 9 * * *"},
        **defaults,
    )


# -- Lifecycle -----------------------------------------------------------------


async def test_start_and_stop(engine: SchedulerEngine) -> None:
    await engine.start()
    assert engine.running is True

    await engine.stop()
    assert engine.running is False


async def test_start_loads_active_tasks(engine: SchedulerEngine, store: TaskStore) -> None:
    await store.add_task(_make_task("t1"))
    await store.add_task(_make_task("t2"))

    await engine.start()
    try:
        jobs = engine._scheduler.get_jobs()
        job_ids = {j.id for j in jobs}
        assert "t1" in job_ids
        assert "t2" in job_ids
    finally:
        await engine.stop()


async def test_stop_when_not_running(engine: SchedulerEngine) -> None:
    # Should not raise
    await engine.stop()


# -- schedule_task -------------------------------------------------------------


async def test_schedule_task_persists_and_adds_job(
    engine: SchedulerEngine, store: TaskStore
) -> None:
    await engine.start()
    try:
        task = _make_task("new1")
        await engine.schedule_task(task)

        # Persisted in store
        fetched = await store.get_task("new1")
        assert fetched is not None
        assert fetched.name == "Test Task"

        # Added to scheduler
        job = engine._scheduler.get_job("new1")
        assert job is not None
    finally:
        await engine.stop()


# -- cancel_task ---------------------------------------------------------------


async def test_cancel_task(engine: SchedulerEngine, store: TaskStore) -> None:
    await store.add_task(_make_task("t1"))
    await engine.start()
    try:
        result = await engine.cancel_task("t1")
        assert result is True

        # Removed from scheduler
        assert engine._scheduler.get_job("t1") is None

        # Deactivated in store
        task = await store.get_task("t1")
        assert task is not None
        assert task.active is False
        assert task.next_run_at is None
    finally:
        await engine.stop()


async def test_cancel_nonexistent_task(engine: SchedulerEngine) -> None:
    await engine.start()
    try:
        result = await engine.cancel_task("nope")
        assert result is False
    finally:
        await engine.stop()


# -- reload --------------------------------------------------------------------


async def test_reload(engine: SchedulerEngine, store: TaskStore) -> None:
    await store.add_task(_make_task("t1"))
    await engine.start()
    try:
        # Add another task directly to the store (simulating external change)
        await store.add_task(_make_task("t2"))

        await engine.reload()

        job_ids = {j.id for j in engine._scheduler.get_jobs()}
        assert "t1" in job_ids
        assert "t2" in job_ids
    finally:
        await engine.stop()


# -- Trigger building ----------------------------------------------------------


def test_build_trigger_one_off(engine: SchedulerEngine) -> None:
    from apscheduler.triggers.date import DateTrigger

    task = _make_task(task_type="one_off", schedule={"run_at": "2025-06-01T09:00:00"})
    trigger = engine._build_trigger(task)
    assert isinstance(trigger, DateTrigger)


def test_build_trigger_cron_string(engine: SchedulerEngine) -> None:
    from apscheduler.triggers.cron import CronTrigger

    task = _make_task(task_type="recurring", schedule={"cron": "0 9 * * *"})
    trigger = engine._build_trigger(task)
    assert isinstance(trigger, CronTrigger)


def test_build_trigger_cron_fields(engine: SchedulerEngine) -> None:
    from apscheduler.triggers.cron import CronTrigger

    task = _make_task(
        task_type="recurring",
        schedule={"hour": 9, "minute": 0, "day_of_week": "mon-fri"},
    )
    trigger = engine._build_trigger(task)
    assert isinstance(trigger, CronTrigger)


# -- _run_task bookkeeping -----------------------------------------------------


async def test_run_task_deactivates_one_off(
    engine: SchedulerEngine, store: TaskStore, executor: TaskExecutor
) -> None:
    task = _make_task("t1", task_type="one_off", schedule={"run_at": "2025-06-01T09:00:00"})
    # Start the engine BEFORE adding the task to the store so that APScheduler
    # doesn't auto-load and immediately fire the past-date one_off trigger.
    await engine.start()
    try:
        await store.add_task(task)
        await engine._run_task("t1")

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.active is False
        assert updated.next_run_at is None
    finally:
        await engine.stop()


async def test_run_task_updates_next_run_for_recurring(
    engine: SchedulerEngine, store: TaskStore
) -> None:
    task = _make_task("t1", task_type="recurring", schedule={"cron": "0 9 * * *"})
    await store.add_task(task)
    await engine.start()
    try:
        await engine._run_task("t1")

        updated = await store.get_task("t1")
        assert updated is not None
        # Should still be active
        assert updated.active is True
        # next_run_at should be set (scheduler calculates next run time)
        assert updated.next_run_at is not None
    finally:
        await engine.stop()
