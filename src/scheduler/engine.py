"""SchedulerEngine — APScheduler lifecycle and job management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from src.config import settings

if TYPE_CHECKING:
    from src.scheduler.executor import TaskExecutor
    from src.scheduler.models import ScheduledTask
    from src.scheduler.store import TaskStore

logger = logging.getLogger(__name__)


class SchedulerEngine:
    """Manages the APScheduler lifecycle and maps ScheduledTasks to jobs.

    Args:
        store: TaskStore for persistence.
        executor: TaskExecutor to run tasks.
        timezone: IANA timezone string (default from settings).
    """

    def __init__(
        self,
        store: TaskStore,
        executor: TaskExecutor,
        timezone: str | None = None,
    ) -> None:
        self._store = store
        self._executor = executor
        self._timezone = timezone or settings.scheduler_timezone
        self._scheduler = AsyncIOScheduler(timezone=self._timezone)
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    # -- Lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        """Load active tasks from the store, create jobs, and start the scheduler."""
        tasks = await self._store.list_active_tasks()
        for task in tasks:
            self._add_job(task)
        self._scheduler.start()
        self._running = True
        logger.info(
            "Scheduler started with %d active task(s) (tz=%s)",
            len(tasks),
            self._timezone,
        )

    async def stop(self) -> None:
        """Shut down the scheduler."""
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("Scheduler stopped")

    # -- Task management -------------------------------------------------------

    async def schedule_task(self, task: ScheduledTask) -> ScheduledTask:
        """Persist a task and add it to the live scheduler."""
        await self._store.add_task(task)
        job = self._add_job(task)
        if job and job.next_run_time:
            await self._store.update_next_run(task.id, job.next_run_time.isoformat())
        logger.info("Scheduled task: %s (%s)", task.name, task.id)
        return task

    async def cancel_task(self, task_id: str) -> bool:
        """Remove a task from the scheduler and deactivate it in the store."""
        try:
            self._scheduler.remove_job(task_id)
        except Exception:
            logger.debug("Job %s not found in scheduler (may already be removed)", task_id)
        deactivated = await self._store.deactivate_task(task_id)
        if deactivated:
            await self._store.update_next_run(task_id, None)
            logger.info("Cancelled task: %s", task_id)
        return deactivated

    async def reload(self) -> None:
        """Remove all jobs and re-load from the store."""
        self._scheduler.remove_all_jobs()
        tasks = await self._store.list_active_tasks()
        for task in tasks:
            job = self._add_job(task)
            if job and job.next_run_time:
                await self._store.update_next_run(task.id, job.next_run_time.isoformat())
        logger.info("Reloaded %d task(s)", len(tasks))

    # -- Internal --------------------------------------------------------------

    def _add_job(self, task: ScheduledTask):
        """Create an APScheduler job for the given task. Returns the Job."""
        trigger = self._build_trigger(task)
        job = self._scheduler.add_job(
            self._run_task,
            trigger=trigger,
            id=task.id,
            name=task.name,
            args=[task.id],
            misfire_grace_time=None,
            replace_existing=True,
        )
        return job

    async def _run_task(self, task_id: str) -> None:
        """Callback invoked by APScheduler. Delegates to the executor."""
        await self._executor.execute(task_id)

        # Post-execution bookkeeping
        task = await self._store.get_task(task_id)
        if task is None:
            return

        if task.is_one_off:
            await self._store.deactivate_task(task_id)
            await self._store.update_next_run(task_id, None)
        else:
            job = self._scheduler.get_job(task_id)
            if job and job.next_run_time:
                await self._store.update_next_run(task_id, job.next_run_time.isoformat())

    def _build_trigger(self, task: ScheduledTask):
        """Convert a task's schedule dict into an APScheduler trigger."""
        schedule = task.schedule

        if task.is_one_off:
            return DateTrigger(run_date=schedule["run_at"], timezone=self._timezone)

        # Recurring — crontab string
        if "cron" in schedule:
            return CronTrigger.from_crontab(schedule["cron"], timezone=self._timezone)

        # Recurring — individual fields (hour, minute, day_of_week, etc.)
        field_names = {"year", "month", "day", "week", "day_of_week", "hour", "minute", "second"}
        cron_kwargs = {k: v for k, v in schedule.items() if k in field_names}
        return CronTrigger(timezone=self._timezone, **cron_kwargs)
