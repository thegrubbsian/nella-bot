"""Tests for scheduler tools — schedule, list, cancel."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.notifications.context import MessageContext
from src.scheduler.engine import SchedulerEngine
from src.scheduler.executor import TaskExecutor
from src.scheduler.store import TaskStore
from src.tools.base import ToolResult
from src.tools.scheduler_tools import (
    cancel_scheduled_task,
    init_scheduler_tools,
    list_scheduled_tasks,
    schedule_task,
)


@pytest.fixture(autouse=True)
def _no_turso(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests use local file, not remote Turso."""
    monkeypatch.setattr("src.config.settings.turso_database_url", "")


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
    eng = SchedulerEngine(store=store, executor=executor, timezone="America/Chicago")
    await eng.start()
    init_scheduler_tools(eng)
    yield eng
    await eng.stop()


@pytest.fixture
def msg_context() -> MessageContext:
    return MessageContext(
        user_id="12345",
        source_channel="telegram",
        reply_channel="telegram",
    )


# -- schedule_task -------------------------------------------------------------


async def test_schedule_one_off(engine: SchedulerEngine, msg_context: MessageContext) -> None:
    result = await schedule_task(
        name="Test reminder",
        task_type="one_off",
        action_type="simple_message",
        action_content="Check the plants!",
        run_at="2099-06-01T15:00:00-06:00",
        msg_context=msg_context,
    )
    assert isinstance(result, ToolResult)
    assert result.success
    assert result.data["scheduled"] is True
    assert result.data["name"] == "Test reminder"
    assert result.data["task_type"] == "one_off"
    assert result.data["action_type"] == "simple_message"


async def test_schedule_recurring_cron(
    engine: SchedulerEngine, msg_context: MessageContext
) -> None:
    result = await schedule_task(
        name="Morning check",
        task_type="recurring",
        action_type="ai_task",
        action_content="Check my email",
        cron="0 8 * * *",
        msg_context=msg_context,
    )
    assert result.success
    assert result.data["task_type"] == "recurring"
    assert result.data["action_type"] == "ai_task"
    assert result.data["next_run_at"] is not None


async def test_schedule_one_off_missing_run_at(engine: SchedulerEngine) -> None:
    result = await schedule_task(
        name="Bad task",
        task_type="one_off",
        action_type="simple_message",
        action_content="hi",
    )
    assert not result.success
    assert "run_at" in result.error


async def test_schedule_recurring_missing_cron(engine: SchedulerEngine) -> None:
    result = await schedule_task(
        name="Bad task",
        task_type="recurring",
        action_type="simple_message",
        action_content="hi",
    )
    assert not result.success
    assert "cron" in result.error


async def test_schedule_invalid_task_type(engine: SchedulerEngine) -> None:
    result = await schedule_task(
        name="Bad",
        task_type="invalid",
        action_type="simple_message",
        action_content="hi",
    )
    assert not result.success
    assert "task_type" in result.error


async def test_schedule_invalid_action_type(engine: SchedulerEngine) -> None:
    result = await schedule_task(
        name="Bad",
        task_type="one_off",
        action_type="invalid",
        action_content="hi",
        run_at="2099-01-01T00:00:00",
    )
    assert not result.success
    assert "action_type" in result.error


async def test_schedule_defaults_channel_from_context(
    engine: SchedulerEngine, msg_context: MessageContext, store: TaskStore
) -> None:
    result = await schedule_task(
        name="Channel test",
        task_type="one_off",
        action_type="simple_message",
        action_content="hi",
        run_at="2099-06-01T15:00:00",
        msg_context=msg_context,
    )
    assert result.success
    task = await store.get_task(result.data["task_id"])
    assert task is not None
    assert task.notification_channel == "telegram"


async def test_schedule_with_description(engine: SchedulerEngine) -> None:
    result = await schedule_task(
        name="Described task",
        task_type="one_off",
        action_type="simple_message",
        action_content="hi",
        description="A detailed description",
        run_at="2099-06-01T15:00:00",
    )
    assert result.success


# -- list_scheduled_tasks ------------------------------------------------------


async def test_list_empty(engine: SchedulerEngine) -> None:
    result = await list_scheduled_tasks()
    assert result.success
    assert result.data["count"] == 0
    assert result.data["tasks"] == []


async def test_list_returns_tasks(engine: SchedulerEngine) -> None:
    await schedule_task(
        name="Task A",
        task_type="recurring",
        action_type="simple_message",
        action_content="hello",
        cron="0 9 * * *",
    )
    await schedule_task(
        name="Task B",
        task_type="one_off",
        action_type="ai_task",
        action_content="do stuff",
        run_at="2099-01-01T00:00:00",
    )

    result = await list_scheduled_tasks()
    assert result.success
    assert result.data["count"] == 2
    names = {t["name"] for t in result.data["tasks"]}
    assert names == {"Task A", "Task B"}


async def test_list_task_fields(engine: SchedulerEngine) -> None:
    await schedule_task(
        name="Detailed task",
        task_type="recurring",
        action_type="simple_message",
        action_content="hi",
        cron="0 8 * * *",
        description="A test task",
    )
    result = await list_scheduled_tasks()
    task = result.data["tasks"][0]
    assert "id" in task
    assert task["name"] == "Detailed task"
    assert task["description"] == "A test task"
    assert task["task_type"] == "recurring"
    assert task["action_type"] == "simple_message"
    assert task["schedule"] == {"cron": "0 8 * * *"}
    assert task["next_run_at"] is not None


# -- cancel_scheduled_task -----------------------------------------------------


async def test_cancel_by_id(engine: SchedulerEngine) -> None:
    created = await schedule_task(
        name="To cancel",
        task_type="one_off",
        action_type="simple_message",
        action_content="hi",
        run_at="2099-01-01T00:00:00",
    )
    task_id = created.data["task_id"]

    result = await cancel_scheduled_task(task_id=task_id)
    assert result.success
    assert result.data["cancelled"] is True


async def test_cancel_by_id_not_found(engine: SchedulerEngine) -> None:
    result = await cancel_scheduled_task(task_id="nonexistent")
    assert not result.success
    assert "not found" in result.error


async def test_cancel_by_search_single_match(engine: SchedulerEngine) -> None:
    await schedule_task(
        name="Water the plants",
        task_type="recurring",
        action_type="simple_message",
        action_content="Water them!",
        cron="0 8 * * *",
    )
    result = await cancel_scheduled_task(search_query="plants")
    assert result.success
    assert result.data["cancelled"] is True
    assert result.data["name"] == "Water the plants"


async def test_cancel_by_search_no_match(engine: SchedulerEngine) -> None:
    result = await cancel_scheduled_task(search_query="nonexistent")
    assert result.success
    assert result.data["cancelled"] is False
    assert "No active tasks" in result.data["message"]


async def test_cancel_by_search_multiple_matches(engine: SchedulerEngine) -> None:
    await schedule_task(
        name="Morning plants check",
        task_type="recurring",
        action_type="simple_message",
        action_content="Check plants",
        cron="0 8 * * *",
    )
    await schedule_task(
        name="Evening plants water",
        task_type="recurring",
        action_type="simple_message",
        action_content="Water plants",
        cron="0 18 * * *",
    )
    result = await cancel_scheduled_task(search_query="plants")
    assert result.success
    assert result.data["cancelled"] is False
    assert len(result.data["matches"]) == 2


async def test_cancel_no_args(engine: SchedulerEngine) -> None:
    result = await cancel_scheduled_task()
    assert not result.success
    assert "task_id or search_query" in result.error
