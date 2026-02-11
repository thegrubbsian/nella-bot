"""Tests for TaskExecutor — dispatches scheduled task actions."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.scheduler.executor import TaskExecutor
from src.scheduler.models import ScheduledTask
from src.scheduler.store import TaskStore


@pytest.fixture(autouse=True)
def _no_turso(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests use local file, not remote Turso."""
    monkeypatch.setattr("src.config.settings.turso_database_url", "")


@pytest.fixture
async def store(tmp_path: Path) -> TaskStore:
    return TaskStore(db_path=tmp_path / "test.db")


@pytest.fixture
def router() -> AsyncMock:
    r = AsyncMock()
    r.send = AsyncMock(return_value=True)
    return r


@pytest.fixture
def generate_response() -> AsyncMock:
    return AsyncMock(return_value="AI response text")


@pytest.fixture
def executor(router: AsyncMock, generate_response: AsyncMock, store: TaskStore) -> TaskExecutor:
    return TaskExecutor(
        router=router,
        generate_response=generate_response,
        store=store,
        owner_user_id="12345",
    )


def _make_task(
    task_id: str = "task1",
    action: dict | None = None,
    **kwargs,
) -> ScheduledTask:
    defaults = {
        "name": "Test Task",
        "task_type": "one_off",
        "schedule": {"run_at": "2025-06-01T09:00:00"},
        "action": action or {"type": "simple_message", "message": "Hello!"},
        "created_at": "2025-01-01T00:00:00",
    }
    defaults.update(kwargs)
    return ScheduledTask(id=task_id, **defaults)


# -- simple_message ------------------------------------------------------------


async def test_simple_message(executor: TaskExecutor, store: TaskStore, router: AsyncMock) -> None:
    task = _make_task(action={"type": "simple_message", "message": "Water the plants!"})
    await store.add_task(task)

    await executor.execute("task1")

    router.send.assert_called_once_with("12345", "Water the plants!", channel=None)
    # last_run_at should be updated
    updated = await store.get_task("task1")
    assert updated is not None
    assert updated.last_run_at is not None


async def test_simple_message_with_channel(
    executor: TaskExecutor, store: TaskStore, router: AsyncMock
) -> None:
    task = _make_task(
        action={"type": "simple_message", "message": "hi"},
        notification_channel="telegram",
    )
    await store.add_task(task)

    await executor.execute("task1")

    router.send.assert_called_once_with("12345", "hi", channel="telegram")


# -- ai_task -------------------------------------------------------------------


async def test_ai_task(
    executor: TaskExecutor,
    store: TaskStore,
    router: AsyncMock,
    generate_response: AsyncMock,
) -> None:
    task = _make_task(action={"type": "ai_task", "prompt": "Check my email"})
    await store.add_task(task)

    await executor.execute("task1")

    generate_response.assert_called_once_with([{"role": "user", "content": "Check my email"}])
    router.send.assert_called_once_with("12345", "AI response text", channel=None)


# -- Edge cases ----------------------------------------------------------------


async def test_task_not_found(executor: TaskExecutor, router: AsyncMock) -> None:
    await executor.execute("nonexistent")
    router.send.assert_not_called()


async def test_inactive_task_skipped(
    executor: TaskExecutor, store: TaskStore, router: AsyncMock
) -> None:
    task = _make_task(active=False)
    await store.add_task(task)

    await executor.execute("task1")

    router.send.assert_not_called()


async def test_unknown_action_type_sends_error(
    executor: TaskExecutor, store: TaskStore, router: AsyncMock
) -> None:
    task = _make_task(action={"type": "unknown_type"})
    await store.add_task(task)

    await executor.execute("task1")

    # Should send an error notification, not crash
    assert router.send.call_count == 1
    call_args = router.send.call_args
    assert "[Scheduler Error]" in call_args[0][1]


async def test_empty_message_does_not_send(
    executor: TaskExecutor, store: TaskStore, router: AsyncMock
) -> None:
    task = _make_task(action={"type": "simple_message", "message": ""})
    await store.add_task(task)

    await executor.execute("task1")

    router.send.assert_not_called()


async def test_empty_prompt_does_not_call_llm(
    executor: TaskExecutor,
    store: TaskStore,
    router: AsyncMock,
    generate_response: AsyncMock,
) -> None:
    task = _make_task(action={"type": "ai_task", "prompt": ""})
    await store.add_task(task)

    await executor.execute("task1")

    generate_response.assert_not_called()
    router.send.assert_not_called()


async def test_llm_failure_sends_error(
    executor: TaskExecutor,
    store: TaskStore,
    router: AsyncMock,
    generate_response: AsyncMock,
) -> None:
    generate_response.side_effect = RuntimeError("API down")
    task = _make_task(action={"type": "ai_task", "prompt": "do stuff"})
    await store.add_task(task)

    await executor.execute("task1")

    # Error notification sent
    assert router.send.call_count == 1
    assert "[Scheduler Error]" in router.send.call_args[0][1]

    # last_run_at should NOT be updated on failure
    updated = await store.get_task("task1")
    assert updated is not None
    assert updated.last_run_at is None
