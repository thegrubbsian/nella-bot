"""Tests for ScheduledTask data model."""

import json

from src.scheduler.models import ScheduledTask, make_task_id

# -- Construction & defaults ---------------------------------------------------


def test_auto_created_at() -> None:
    task = ScheduledTask(
        id="abc123",
        name="Test",
        task_type="one_off",
        schedule={"run_at": "2025-06-01T09:00:00"},
        action={"type": "simple_message", "message": "hi"},
    )
    assert task.created_at != ""
    assert "T" in task.created_at  # ISO 8601


def test_explicit_created_at_not_overwritten() -> None:
    task = ScheduledTask(
        id="abc",
        name="Test",
        task_type="one_off",
        schedule={"run_at": "2025-06-01T09:00:00"},
        action={"type": "simple_message", "message": "hi"},
        created_at="2024-01-01T00:00:00",
    )
    assert task.created_at == "2024-01-01T00:00:00"


def test_default_values() -> None:
    task = ScheduledTask(
        id="abc",
        name="Test",
        task_type="one_off",
        schedule={},
        action={"type": "simple_message", "message": "hi"},
    )
    assert task.description == ""
    assert task.notification_channel is None
    assert task.active is True
    assert task.last_run_at is None
    assert task.next_run_at is None


# -- Properties ----------------------------------------------------------------


def test_action_type() -> None:
    task = ScheduledTask(
        id="1",
        name="t",
        task_type="one_off",
        schedule={},
        action={"type": "ai_task", "prompt": "do stuff"},
    )
    assert task.action_type == "ai_task"


def test_action_type_missing_key() -> None:
    task = ScheduledTask(
        id="1",
        name="t",
        task_type="one_off",
        schedule={},
        action={},
    )
    assert task.action_type == ""


def test_is_one_off() -> None:
    task = ScheduledTask(
        id="1",
        name="t",
        task_type="one_off",
        schedule={},
        action={},
    )
    assert task.is_one_off is True
    assert task.is_recurring is False


def test_is_recurring() -> None:
    task = ScheduledTask(
        id="1",
        name="t",
        task_type="recurring",
        schedule={"cron": "0 9 * * *"},
        action={},
    )
    assert task.is_recurring is True
    assert task.is_one_off is False


# -- Serialization round-trip --------------------------------------------------


def test_to_row_and_from_row_roundtrip() -> None:
    original = ScheduledTask(
        id="deadbeef",
        name="Morning check",
        task_type="recurring",
        schedule={"cron": "0 9 * * *"},
        action={"type": "ai_task", "prompt": "Check my email"},
        description="Every morning at 9",
        notification_channel="telegram",
        active=True,
        created_at="2025-01-01T00:00:00",
        last_run_at="2025-01-02T09:00:00",
        next_run_at="2025-01-03T09:00:00",
    )
    row = original.to_row()
    restored = ScheduledTask.from_row(row)

    assert restored.id == original.id
    assert restored.name == original.name
    assert restored.task_type == original.task_type
    assert restored.schedule == original.schedule
    assert restored.action == original.action
    assert restored.description == original.description
    assert restored.notification_channel == original.notification_channel
    assert restored.active == original.active
    assert restored.created_at == original.created_at
    assert restored.last_run_at == original.last_run_at
    assert restored.next_run_at == original.next_run_at


def test_to_row_json_fields() -> None:
    task = ScheduledTask(
        id="1",
        name="t",
        task_type="one_off",
        schedule={"run_at": "2025-06-01T09:00:00"},
        action={"type": "simple_message", "message": "hello"},
    )
    row = task.to_row()
    # schedule and action are JSON strings in positions 3 and 4
    assert json.loads(row[3]) == {"run_at": "2025-06-01T09:00:00"}
    assert json.loads(row[4]) == {"type": "simple_message", "message": "hello"}


def test_from_row_inactive_task() -> None:
    row = (
        "id1",
        "name",
        "one_off",
        '{"run_at": "2025-01-01"}',
        '{"type": "simple_message", "message": "hi"}',
        "",
        None,
        0,  # active = 0
        "2025-01-01T00:00:00",
        None,
        None,
    )
    task = ScheduledTask.from_row(row)
    assert task.active is False


def test_from_row_null_description() -> None:
    row = (
        "id1",
        "name",
        "one_off",
        "{}",
        "{}",
        None,
        None,
        1,
        "2025-01-01T00:00:00",
        None,
        None,
    )
    task = ScheduledTask.from_row(row)
    assert task.description == ""


# -- make_task_id --------------------------------------------------------------


def test_make_task_id_is_hex_string() -> None:
    tid = make_task_id()
    assert isinstance(tid, str)
    assert len(tid) == 32  # UUID hex
    int(tid, 16)  # Should not raise


def test_make_task_id_unique() -> None:
    ids = {make_task_id() for _ in range(100)}
    assert len(ids) == 100
