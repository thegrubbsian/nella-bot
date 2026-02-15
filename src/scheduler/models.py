"""ScheduledTask data model."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class ScheduledTask:
    """A task to be executed on a schedule.

    Attributes:
        id: Unique identifier (UUID hex).
        name: Human-readable name.
        task_type: Either ``"one_off"`` or ``"recurring"``.
        schedule: Timing config — ``{"run_at": "ISO"}`` for one-off,
            ``{"cron": "* * * * *"}`` or field-based ``{"hour": 9}`` for recurring.
        action: What to do — ``{"type": "simple_message", "message": "..."}``
            or ``{"type": "ai_task", "prompt": "..."}``.
        description: Optional human-readable description.
        notification_channel: Channel name override (None → default).
        model: Claude model override for ai_task execution (None → global default).
        active: Whether the task is scheduled.
        created_at: ISO 8601 timestamp.
        last_run_at: ISO 8601 timestamp of the last execution.
        next_run_at: ISO 8601 timestamp of the next planned execution.
    """

    id: str
    name: str
    task_type: str
    schedule: dict[str, Any]
    action: dict[str, Any]
    description: str = ""
    notification_channel: str | None = None
    model: str | None = None
    active: bool = True
    created_at: str = ""
    last_run_at: str | None = None
    next_run_at: str | None = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    # -- Convenience properties ------------------------------------------------

    @property
    def action_type(self) -> str:
        """Return the action type: ``"simple_message"``, ``"ai_task"``, etc."""
        return str(self.action.get("type", ""))

    @property
    def is_one_off(self) -> bool:
        return self.task_type == "one_off"

    @property
    def is_recurring(self) -> bool:
        return self.task_type == "recurring"

    # -- Serialization ---------------------------------------------------------

    def to_row(self) -> tuple:
        """Serialize to a tuple matching the ``scheduled_tasks`` column order."""
        return (
            self.id,
            self.name,
            self.task_type,
            json.dumps(self.schedule),
            json.dumps(self.action),
            self.description,
            self.notification_channel,
            self.model,
            int(self.active),
            self.created_at,
            self.last_run_at,
            self.next_run_at,
        )

    @classmethod
    def from_row(cls, row: tuple) -> ScheduledTask:
        """Deserialize from a SQLite row tuple."""
        # Handle rows from databases that predate the model column (11 elements)
        has_model = len(row) > 11
        if has_model:
            return cls(
                id=row[0],
                name=row[1],
                task_type=row[2],
                schedule=json.loads(row[3]),
                action=json.loads(row[4]),
                description=row[5] or "",
                notification_channel=row[6],
                model=row[7],
                active=bool(row[8]),
                created_at=row[9],
                last_run_at=row[10],
                next_run_at=row[11],
            )
        return cls(
            id=row[0],
            name=row[1],
            task_type=row[2],
            schedule=json.loads(row[3]),
            action=json.loads(row[4]),
            description=row[5] or "",
            notification_channel=row[6],
            active=bool(row[7]),
            created_at=row[8],
            last_run_at=row[9],
            next_run_at=row[10],
        )


def make_task_id() -> str:
    """Generate a new task ID."""
    return uuid.uuid4().hex
