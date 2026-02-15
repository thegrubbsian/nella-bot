"""Tests for TaskStore — libsql CRUD."""

from pathlib import Path

import pytest

from src.scheduler.models import ScheduledTask
from src.scheduler.store import TaskStore

pytestmark = pytest.mark.usefixtures("_no_turso")


@pytest.fixture
async def store(tmp_path: Path) -> TaskStore:
    """Create a TaskStore backed by a temp database."""
    return TaskStore(db_path=tmp_path / "test.db")


def _make_task(
    task_id: str = "task1",
    name: str = "Test Task",
    task_type: str = "one_off",
    **kwargs,
) -> ScheduledTask:
    defaults = {
        "schedule": {"run_at": "2025-06-01T09:00:00"},
        "action": {"type": "simple_message", "message": "hello"},
        "created_at": "2025-01-01T00:00:00",
    }
    defaults.update(kwargs)
    return ScheduledTask(id=task_id, name=name, task_type=task_type, **defaults)


# -- add_task / get_task -------------------------------------------------------


async def test_add_and_get_task(store: TaskStore) -> None:
    task = _make_task()
    await store.add_task(task)

    fetched = await store.get_task("task1")
    assert fetched is not None
    assert fetched.id == "task1"
    assert fetched.name == "Test Task"
    assert fetched.action == {"type": "simple_message", "message": "hello"}


async def test_get_task_not_found(store: TaskStore) -> None:
    result = await store.get_task("nonexistent")
    assert result is None


# -- list_active_tasks ---------------------------------------------------------


async def test_list_active_tasks(store: TaskStore) -> None:
    await store.add_task(_make_task("t1", "Task 1"))
    await store.add_task(_make_task("t2", "Task 2"))
    await store.add_task(_make_task("t3", "Task 3", active=False))

    active = await store.list_active_tasks()
    ids = [t.id for t in active]
    assert "t1" in ids
    assert "t2" in ids
    assert "t3" not in ids


async def test_list_active_tasks_empty(store: TaskStore) -> None:
    active = await store.list_active_tasks()
    assert active == []


# -- deactivate_task -----------------------------------------------------------


async def test_deactivate_task(store: TaskStore) -> None:
    await store.add_task(_make_task("t1"))

    result = await store.deactivate_task("t1")
    assert result is True

    task = await store.get_task("t1")
    assert task is not None
    assert task.active is False


async def test_deactivate_nonexistent_returns_false(store: TaskStore) -> None:
    result = await store.deactivate_task("nonexistent")
    assert result is False


# -- update_last_run -----------------------------------------------------------


async def test_update_last_run(store: TaskStore) -> None:
    await store.add_task(_make_task("t1"))
    await store.update_last_run("t1", "2025-06-01T10:00:00")

    task = await store.get_task("t1")
    assert task is not None
    assert task.last_run_at == "2025-06-01T10:00:00"


async def test_update_last_run_default_timestamp(store: TaskStore) -> None:
    await store.add_task(_make_task("t1"))
    await store.update_last_run("t1")

    task = await store.get_task("t1")
    assert task is not None
    assert task.last_run_at is not None
    assert "T" in task.last_run_at


# -- update_next_run -----------------------------------------------------------


async def test_update_next_run(store: TaskStore) -> None:
    await store.add_task(_make_task("t1"))
    await store.update_next_run("t1", "2025-06-02T09:00:00")

    task = await store.get_task("t1")
    assert task is not None
    assert task.next_run_at == "2025-06-02T09:00:00"


async def test_update_next_run_clear(store: TaskStore) -> None:
    await store.add_task(_make_task("t1"))
    await store.update_next_run("t1", "2025-06-02T09:00:00")
    await store.update_next_run("t1", None)

    task = await store.get_task("t1")
    assert task is not None
    assert task.next_run_at is None


# -- model persistence --------------------------------------------------------


async def test_model_persists_through_add_get(store: TaskStore) -> None:
    task = _make_task("t1", model="claude-opus-4-6-20250612")
    await store.add_task(task)

    fetched = await store.get_task("t1")
    assert fetched is not None
    assert fetched.model == "claude-opus-4-6-20250612"


async def test_model_none_by_default(store: TaskStore) -> None:
    task = _make_task("t1")
    await store.add_task(task)

    fetched = await store.get_task("t1")
    assert fetched is not None
    assert fetched.model is None


# -- update_task_model ---------------------------------------------------------


async def test_update_task_model(store: TaskStore) -> None:
    await store.add_task(_make_task("t1"))
    result = await store.update_task_model("t1", "claude-haiku-4-5-20251001")

    assert result is True
    task = await store.get_task("t1")
    assert task is not None
    assert task.model == "claude-haiku-4-5-20251001"


async def test_update_task_model_clear(store: TaskStore) -> None:
    await store.add_task(_make_task("t1", model="claude-opus-4-6-20250612"))
    result = await store.update_task_model("t1", None)

    assert result is True
    task = await store.get_task("t1")
    assert task is not None
    assert task.model is None


async def test_update_task_model_inactive_returns_false(store: TaskStore) -> None:
    await store.add_task(_make_task("t1", active=False))
    result = await store.update_task_model("t1", "claude-opus-4-6-20250612")
    assert result is False


async def test_update_task_model_nonexistent_returns_false(store: TaskStore) -> None:
    result = await store.update_task_model("nonexistent", "claude-opus-4-6-20250612")
    assert result is False


# -- Singleton -----------------------------------------------------------------


def test_singleton_get() -> None:
    TaskStore._reset()
    try:
        a = TaskStore.get()
        b = TaskStore.get()
        assert a is b
    finally:
        TaskStore._reset()


def test_singleton_reset() -> None:
    TaskStore._reset()
    try:
        a = TaskStore.get()
        TaskStore._reset()
        b = TaskStore.get()
        assert a is not b
    finally:
        TaskStore._reset()
