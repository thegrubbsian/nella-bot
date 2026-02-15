"""TaskExecutor — dispatches scheduled task actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.notifications.router import NotificationRouter
    from src.scheduler.models import ScheduledTask
    from src.scheduler.store import TaskStore

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Executes scheduled tasks by dispatching to the appropriate handler.

    Args:
        router: NotificationRouter for sending messages.
        generate_response: Async callable ``(messages, model)`` that runs the
            LLM pipeline and returns the assistant's response text.
        store: TaskStore for updating last_run_at.
        owner_user_id: The bot owner's user ID (for routing notifications).
    """

    def __init__(
        self,
        router: NotificationRouter,
        generate_response: Callable[[list[dict], str | None], Awaitable[str]],
        store: TaskStore,
        owner_user_id: str,
    ) -> None:
        self._router = router
        self._generate_response = generate_response
        self._store = store
        self._owner_user_id = owner_user_id

    async def execute(self, task_id: str) -> None:
        """Look up and execute a scheduled task by ID."""
        task = await self._store.get_task(task_id)
        if task is None:
            logger.warning("Scheduled task not found: %s", task_id)
            return
        if not task.active:
            logger.info("Skipping inactive task: %s (%s)", task.name, task_id)
            return

        logger.info(
            "Executing task: '%s' (%s) action=%s channel=%s",
            task.name,
            task_id,
            task.action_type,
            task.notification_channel,
        )
        try:
            await self._dispatch(task)
            await self._store.update_last_run(task_id)
            logger.info("Task executed successfully: '%s' (%s)", task.name, task_id)
        except Exception:
            logger.exception("Task execution failed: '%s' (%s)", task.name, task_id)
            await self._send_error(task, task_id)

    async def _dispatch(self, task: ScheduledTask) -> None:
        """Route to the correct handler based on action type."""
        action_type = task.action_type
        if action_type == "simple_message":
            await self._handle_simple_message(task)
        elif action_type == "ai_task":
            await self._handle_ai_task(task)
        else:
            msg = f"Unknown action type: {action_type}"
            raise ValueError(msg)

    async def _handle_simple_message(self, task: ScheduledTask) -> None:
        """Send a plain text message."""
        message = task.action.get("message", "")
        if not message:
            logger.warning("simple_message task has empty message: %s", task.id)
            return
        logger.info("Sending simple_message for task '%s' (%d chars)", task.name, len(message))
        await self._router.send(
            self._owner_user_id,
            message,
            channel=task.notification_channel,
        )

    async def _handle_ai_task(self, task: ScheduledTask) -> None:
        """Run a prompt through the LLM and send the result."""
        prompt = task.action.get("prompt", "")
        if not prompt:
            logger.warning("ai_task has empty prompt: %s", task.id)
            return
        logger.info(
            "Running ai_task for '%s' (prompt: %d chars)", task.name, len(prompt)
        )
        messages = [{"role": "user", "content": prompt}]
        response = await self._generate_response(messages, task.model)
        logger.info(
            "ai_task LLM response for '%s' (%d chars)", task.name, len(response)
        )
        await self._router.send(
            self._owner_user_id,
            response,
            channel=task.notification_channel,
        )

    async def _send_error(self, task: ScheduledTask, task_id: str) -> None:
        """Notify the owner about a task failure instead of crashing."""
        error_msg = (
            f"[Scheduler Error] Task '{task.name}' ({task_id}) failed."
            " Check logs for details."
        )
        await self._router.send(
            self._owner_user_id,
            error_msg,
            channel=task.notification_channel,
        )
