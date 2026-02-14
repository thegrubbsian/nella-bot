"""Scheduler tools — create, list, and cancel scheduled tasks."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import Field

from src.scheduler.models import ScheduledTask, make_task_id
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

if TYPE_CHECKING:
    from src.notifications.context import MessageContext
    from src.scheduler.engine import SchedulerEngine

logger = logging.getLogger(__name__)

_CATEGORY = "scheduler"

# Set by init_scheduler_tools() during bot startup.
_engine: SchedulerEngine | None = None


def init_scheduler_tools(engine: SchedulerEngine) -> None:
    """Wire the scheduler engine into the tool functions.

    Called once during bot startup, after the engine is constructed.
    """
    global _engine  # noqa: PLW0603
    _engine = engine


def _get_engine() -> SchedulerEngine:
    if _engine is None:
        msg = "Scheduler not initialised — call init_scheduler_tools() first"
        raise RuntimeError(msg)
    return _engine


# -- schedule_task -------------------------------------------------------------


class ScheduleTaskParams(ToolParams):
    name: str = Field(description="Human-readable name for this task")
    description: str = Field(default="", description="Optional longer description of the task")
    task_type: str = Field(
        description='Either "one_off" (runs once) or "recurring" (runs on a schedule)'
    )
    run_at: str | None = Field(
        default=None,
        description=(
            "ISO 8601 datetime for one-off tasks (e.g. '2025-06-01T15:00:00-06:00'). "
            "Required when task_type is 'one_off'."
        ),
    )
    cron: str | None = Field(
        default=None,
        description=(
            "Cron expression for recurring tasks (e.g. '0 8 * * *' for daily at 8am). "
            "Required when task_type is 'recurring'."
        ),
    )
    action_type: str = Field(
        description=(
            '"simple_message" to send a plain text message, '
            'or "ai_task" to run a prompt through the AI with full tool access'
        )
    )
    action_content: str = Field(
        description=("The message text (for simple_message) or the AI prompt (for ai_task)")
    )
    notification_channel: str | None = Field(
        default=None,
        description="Notification channel override (defaults to current channel)",
    )


@registry.tool(
    name="schedule_task",
    description=(
        "Schedule a task to run at a specific time or on a recurring schedule. "
        "Use 'simple_message' for plain reminders or 'ai_task' for tasks that "
        "need AI reasoning and tool access (e.g. checking email, summarising)."
    ),
    category=_CATEGORY,
    params_model=ScheduleTaskParams,
    requires_confirmation=True,
)
async def schedule_task(
    name: str,
    task_type: str,
    action_type: str,
    action_content: str,
    description: str = "",
    run_at: str | None = None,
    cron: str | None = None,
    notification_channel: str | None = None,
    msg_context: MessageContext | None = None,
) -> ToolResult:
    engine = _get_engine()

    # Validate schedule fields
    if task_type == "one_off" and not run_at:
        return ToolResult(error="run_at is required for one_off tasks")
    if task_type == "recurring" and not cron:
        return ToolResult(error="cron is required for recurring tasks")
    if task_type not in ("one_off", "recurring"):
        return ToolResult(error=f"Invalid task_type: {task_type}")
    if action_type not in ("simple_message", "ai_task"):
        return ToolResult(error=f"Invalid action_type: {action_type}")

    # Build schedule dict
    schedule: dict[str, Any] = {}
    if task_type == "one_off":
        schedule["run_at"] = run_at
    else:
        schedule["cron"] = cron

    # Build action dict
    action: dict[str, str] = {"type": action_type}
    if action_type == "simple_message":
        action["message"] = action_content
    else:
        action["prompt"] = action_content

    # Default notification_channel to the current reply channel
    if notification_channel is None and msg_context is not None:
        notification_channel = msg_context.reply_channel or None

    task = ScheduledTask(
        id=make_task_id(),
        name=name,
        task_type=task_type,
        schedule=schedule,
        action=action,
        description=description,
        notification_channel=notification_channel,
    )

    task = await engine.schedule_task(task)

    # Re-read to get the computed next_run_at
    stored = await engine._store.get_task(task.id)
    next_run = stored.next_run_at if stored else None

    return ToolResult(
        data={
            "scheduled": True,
            "task_id": task.id,
            "name": task.name,
            "task_type": task.task_type,
            "schedule": task.schedule,
            "action_type": action_type,
            "next_run_at": next_run,
        }
    )


# -- list_scheduled_tasks ------------------------------------------------------


@registry.tool(
    name="list_scheduled_tasks",
    description="List all active scheduled tasks with their details and next run time.",
    category=_CATEGORY,
)
async def list_scheduled_tasks() -> ToolResult:
    engine = _get_engine()
    tasks = await engine._store.list_active_tasks()

    if not tasks:
        return ToolResult(data={"tasks": [], "count": 0})

    task_list = []
    for t in tasks:
        task_list.append(
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "task_type": t.task_type,
                "schedule": t.schedule,
                "action_type": t.action_type,
                "action": t.action,
                "notification_channel": t.notification_channel,
                "next_run_at": t.next_run_at,
                "last_run_at": t.last_run_at,
                "created_at": t.created_at,
            }
        )

    return ToolResult(data={"tasks": task_list, "count": len(task_list)})


# -- cancel_scheduled_task -----------------------------------------------------


class CancelScheduledTaskParams(ToolParams):
    task_id: str | None = Field(default=None, description="Exact task ID to cancel")
    search_query: str | None = Field(
        default=None,
        description="Search task names/descriptions to find the task to cancel",
    )


@registry.tool(
    name="cancel_scheduled_task",
    description=(
        "Cancel a scheduled task by ID or by searching task names/descriptions. "
        "If a search matches multiple tasks, returns them so the user can choose."
    ),
    category=_CATEGORY,
    params_model=CancelScheduledTaskParams,
    requires_confirmation=True,
)
async def cancel_scheduled_task(
    task_id: str | None = None,
    search_query: str | None = None,
) -> ToolResult:
    engine = _get_engine()

    if not task_id and not search_query:
        return ToolResult(error="Provide either task_id or search_query")

    # Direct cancel by ID
    if task_id:
        # Normalize: Claude sometimes reformats hex IDs as dashed UUIDs
        task_id = task_id.replace("-", "")
        cancelled = await engine.cancel_task(task_id)
        if cancelled:
            return ToolResult(data={"cancelled": True, "task_id": task_id})
        return ToolResult(error=f"Task not found or already inactive: {task_id}")

    # Search and cancel
    matches = await engine._store.search_active_tasks(search_query)

    if not matches:
        return ToolResult(
            data={
                "cancelled": False,
                "message": f"No active tasks matching '{search_query}'",
            }
        )

    if len(matches) == 1:
        task = matches[0]
        cancelled = await engine.cancel_task(task.id)
        return ToolResult(
            data={
                "cancelled": cancelled,
                "task_id": task.id,
                "name": task.name,
            }
        )

    # Multiple matches — return them for the user to choose
    return ToolResult(
        data={
            "cancelled": False,
            "message": "Multiple tasks match. Ask which one to cancel.",
            "matches": [
                {"id": t.id, "name": t.name, "description": t.description} for t in matches
            ],
        }
    )
