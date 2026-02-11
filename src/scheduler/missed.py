"""Missed scheduled task recovery — detect and notify on startup."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from src.config import settings
from src.notifications.router import NotificationRouter

try:
    import zoneinfo
except ImportError:  # pragma: no cover
    from backports import zoneinfo  # type: ignore[no-redef]

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import CallbackQuery

    from src.scheduler.engine import SchedulerEngine
    from src.scheduler.executor import TaskExecutor

logger = logging.getLogger(__name__)

# Module-level state, set by init_missed_task_recovery() during startup.
_engine: SchedulerEngine | None = None
_executor: TaskExecutor | None = None
_owner_user_id: str = ""
_pending_missed: dict[str, str] = {}  # 8-char key -> full task_id


def init_missed_task_recovery(
    engine: SchedulerEngine,
    executor: TaskExecutor,
    owner_user_id: str,
) -> None:
    """Wire dependencies. Called once during bot startup."""
    global _engine, _executor, _owner_user_id  # noqa: PLW0603
    _engine = engine
    _executor = executor
    _owner_user_id = owner_user_id


def _generate_key() -> str:
    """Return an 8-character hex string for callback data."""
    return uuid.uuid4().hex[:8]


async def check_and_notify_missed_tasks() -> int:
    """Detect missed one-off tasks and send notification for each.

    Returns the number of missed tasks found (useful for testing).
    """
    if _engine is None:
        logger.warning("Missed task recovery not initialised")
        return 0

    tasks = await _engine._store.list_active_tasks()
    tz = zoneinfo.ZoneInfo(settings.scheduler_timezone)
    now = datetime.now(tz)
    missed_count = 0

    for task in tasks:
        if not task.is_one_off:
            continue
        if task.last_run_at is not None:
            continue

        run_at_str = task.schedule.get("run_at")
        if not run_at_str:
            continue

        run_at = datetime.fromisoformat(run_at_str)
        # Attach timezone if naive
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=tz)

        if run_at >= now:
            continue

        # This task was missed
        key = _generate_key()
        _pending_missed[key] = task.id

        formatted_time = run_at.strftime("%Y-%m-%d %H:%M %Z")
        message = (
            f"*Missed scheduled task:* {task.name}\n"
            f"Was scheduled for: {formatted_time}"
        )
        buttons = [[
            {"text": "Run Now", "callback_data": f"mst:{key}:run"},
            {"text": "Delete", "callback_data": f"mst:{key}:del"},
        ]]

        router = NotificationRouter.get()
        await router.send_rich(
            _owner_user_id,
            message,
            buttons=buttons,
            parse_mode="Markdown",
        )
        missed_count += 1
        logger.info("Notified owner about missed task: %s (%s)", task.name, task.id)

    if missed_count:
        logger.info("Found %d missed scheduled task(s)", missed_count)
    return missed_count


async def handle_missed_task_callback(
    query: CallbackQuery,
    conf_key: str,
    action: str,
) -> None:
    """Process a missed-task inline button press (Run Now / Delete)."""
    import contextlib

    task_id = _pending_missed.get(conf_key)

    if task_id is None:
        await query.answer("This notification has expired.")
        with contextlib.suppress(Exception):
            await query.edit_message_text(
                text=query.message.text + "\n\n(expired)",
            )
        return

    if _engine is None or _executor is None:
        await query.answer("Scheduler not available.")
        return

    if action == "run":
        await _executor.execute(task_id)
        await _engine.cancel_task(task_id)
        status_text = "Executed"
    else:  # "del"
        await _engine.cancel_task(task_id)
        status_text = "Deleted"

    _pending_missed.pop(conf_key, None)

    with contextlib.suppress(Exception):
        await query.edit_message_text(
            text=query.message.text + f"\n\n→ {status_text}",
        )
    await query.answer(status_text)
