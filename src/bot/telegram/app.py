"""Telegram application factory."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from src.bot.telegram.handlers import (
    handle_callback_query,
    handle_clear,
    handle_message,
    handle_model,
    handle_start,
    handle_status,
)
from src.config import settings
from src.notifications.router import NotificationRouter
from src.notifications.telegram_channel import TelegramChannel

if TYPE_CHECKING:
    from src.scheduler.engine import SchedulerEngine
    from src.webhooks.server import WebhookServer

logger = logging.getLogger(__name__)

# Module-level references so post_shutdown can access them.
_scheduler_engine: SchedulerEngine | None = None
_webhook_server: WebhookServer | None = None


def _init_notifications(app: Application) -> None:
    """Register notification channels and set the default."""
    router = NotificationRouter.get()
    telegram_channel = TelegramChannel(app.bot)
    router.register_channel(telegram_channel)
    router.set_default_channel(settings.default_notification_channel)
    logger.info(
        "Notifications initialized: channels=%s, default=%s",
        router.list_channels(),
        router.default_channel_name,
    )


def _init_scheduler() -> SchedulerEngine:
    """Create the scheduler engine and wire it into the tool functions."""
    from src.llm.client import generate_response
    from src.scheduler.engine import SchedulerEngine
    from src.scheduler.executor import TaskExecutor
    from src.scheduler.missed import init_missed_task_recovery
    from src.scheduler.store import TaskStore
    from src.tools.scheduler_tools import init_scheduler_tools

    store = TaskStore.get()
    router = NotificationRouter.get()

    # Resolve owner user ID from allowed users (single-user bot)
    allowed = settings.get_allowed_user_ids()
    owner_user_id = str(next(iter(allowed))) if allowed else ""

    # Simplified generate_response wrapper for the executor:
    # The executor doesn't need streaming or confirmation callbacks.
    async def _scheduler_generate(messages: list[dict]) -> str:
        return await generate_response(messages)

    executor = TaskExecutor(
        router=router,
        generate_response=_scheduler_generate,
        store=store,
        owner_user_id=owner_user_id,
    )
    engine = SchedulerEngine(store=store, executor=executor)

    # Give the scheduler tools access to the engine
    init_scheduler_tools(engine)

    # Wire missed-task recovery (notifications sent in _post_init)
    init_missed_task_recovery(engine, executor, owner_user_id)

    return engine


async def _post_init(app: Application) -> None:
    """Called after the Application is fully initialized (event loop running)."""
    global _scheduler_engine, _webhook_server  # noqa: PLW0603

    from src.scratch import ScratchSpace

    scratch = ScratchSpace.get()
    removed = scratch.cleanup()
    if removed:
        logger.info("Scratch cleanup: removed %d old files", removed)

    _scheduler_engine = _init_scheduler()
    await _scheduler_engine.start()

    # Fire-and-forget: notify owner about missed one-off tasks
    from src.scheduler.missed import check_and_notify_missed_tasks

    asyncio.create_task(check_and_notify_missed_tasks())

    from src.webhooks.server import WebhookServer

    _webhook_server = WebhookServer()
    await _webhook_server.start()

    # Signal systemd that we're fully ready and start the watchdog ping loop
    from src.watchdog import notify_ready, start_watchdog

    notify_ready()
    start_watchdog()


async def _post_shutdown(app: Application) -> None:
    """Called during graceful shutdown."""
    if _webhook_server is not None:
        await _webhook_server.stop()
    if _scheduler_engine is not None:
        await _scheduler_engine.stop()


def create_app() -> Application:
    """Build and configure the Telegram application."""
    app = Application.builder().token(settings.telegram_bot_token).concurrent_updates(True).build()

    _init_notifications(app)

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("clear", handle_clear))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("model", handle_model))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Scheduler lifecycle hooks
    app.post_init = _post_init
    app.post_shutdown = _post_shutdown

    return app
