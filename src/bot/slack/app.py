"""Slack Bolt application factory."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.app.async_app import AsyncApp as App
from slack_sdk.web.async_client import AsyncWebClient

from src.bot.slack.confirmations import get_pending, resolve_confirmation
from src.bot.slack.handlers import (
    handle_clear_command,
    handle_message,
    handle_model_command,
    handle_status_command,
)
from src.config import settings
from src.notifications.router import NotificationRouter
from src.notifications.slack_channel import SlackChannel

if TYPE_CHECKING:
    from src.scheduler.engine import SchedulerEngine
    from src.webhooks.server import WebhookServer

logger = logging.getLogger(__name__)

_scheduler_engine: SchedulerEngine | None = None
_webhook_server: WebhookServer | None = None


def _init_notifications(client: AsyncWebClient) -> None:
    """Register notification channels and set the default."""
    router = NotificationRouter.get()
    slack_channel = SlackChannel(client)
    router.register_channel(slack_channel)
    default_channel = settings.default_notification_channel
    if router.get_channel(default_channel) is None:
        logger.warning(
            "Default notification channel '%s' is not registered; using '%s'",
            default_channel,
            slack_channel.name,
        )
        default_channel = slack_channel.name
    router.set_default_channel(default_channel)
    logger.info(
        "Notifications initialized: channels=%s, default=%s",
        router.list_channels(),
        router.default_channel_name,
    )


def _init_scheduler() -> SchedulerEngine:
    """Create the scheduler engine — same as Telegram's version."""
    from src.llm.client import generate_response
    from src.scheduler.engine import SchedulerEngine
    from src.scheduler.executor import TaskExecutor
    from src.scheduler.missed import init_missed_task_recovery
    from src.scheduler.store import TaskStore

    store = TaskStore.get()
    router = NotificationRouter.get()

    # For Slack, there's no single "owner" — anyone in the workspace can use Nella.
    # Use empty string; scheduler tasks will need an explicit user_id.
    owner_user_id = ""

    async def _scheduler_generate(messages: list[dict]) -> str:
        return await generate_response(messages)

    executor = TaskExecutor(
        router=router,
        generate_response=_scheduler_generate,
        store=store,
        owner_user_id=owner_user_id,
    )
    engine = SchedulerEngine(store=store, executor=executor)

    from src.tools.scheduler_tools import init_scheduler_tools

    init_scheduler_tools(engine)

    init_missed_task_recovery(engine, executor, owner_user_id)

    return engine


def create_slack_app() -> App:
    """Build and configure the Slack Bolt application."""
    client = AsyncWebClient(token=settings.slack_bot_token)
    app = App(token=settings.slack_bot_token, client=client)

    _init_notifications(client)

    # Message handler — only DMs (im), ignore bot messages and message edits
    @app.event("message")
    async def _on_message(event, say, client):
        logger.info(
            "Slack message event received: channel_type=%s user=%s channel=%s text=%s",
            event.get("channel_type"),
            event.get("user"),
            event.get("channel"),
            event.get("text", "")[:120],
        )
        # Skip bot messages, message_changed, etc.
        if event.get("subtype"):
            logger.info("Skipping Slack message event due to subtype=%s", event.get("subtype"))
            return
        # Only handle DMs (channel type "im")
        if event.get("channel_type") != "im":
            logger.info("Skipping Slack message event due to channel_type=%s", event.get("channel_type"))
            return
        await handle_message(event=event, say=say, client=client)

    # Mention handler — allow channel mentions to trigger responses
    @app.event("app_mention")
    async def _on_mention(event, say, client):
        logger.info(
            "Slack app_mention event received: user=%s channel=%s text=%s",
            event.get("user"),
            event.get("channel"),
            event.get("text", "")[:120],
        )
        if event.get("subtype"):
            logger.info("Skipping Slack mention event due to subtype=%s", event.get("subtype"))
            return
        # app_mention only fires in channels; treat as channel response
        await handle_message(event=event, say=say, client=client)

    # Slash commands
    app.command("/nella-clear")(handle_clear_command)
    app.command("/nella-status")(handle_status_command)
    app.command("/nella-model")(handle_model_command)

    # Confirmation button handler
    confirm_re = re.compile(r"^cfm:([a-f0-9]+):(y|n)$")

    @app.action(confirm_re)
    async def _on_confirm_action(ack, action, say):
        await ack()
        action_id = action["action_id"]
        m = confirm_re.match(action_id)
        if not m:
            return
        conf_id, choice = m.group(1), m.group(2)
        pc = get_pending(conf_id)
        if pc is None:
            return
        if pc.future.done():
            return
        approved = choice == "y"
        resolve_confirmation(conf_id, approved=approved)

    return app


def run_slack() -> None:
    """Start the Slack bot with Socket Mode (blocking)."""

    async def _run() -> None:
        global _scheduler_engine, _webhook_server  # noqa: PLW0603

        app = create_slack_app()

        # Start scheduler
        _scheduler_engine = _init_scheduler()
        await _scheduler_engine.start()

        from src.scheduler.missed import check_and_notify_missed_tasks

        asyncio.create_task(check_and_notify_missed_tasks())

        # Start webhook server
        from src.webhooks.server import WebhookServer

        _webhook_server = WebhookServer()
        await _webhook_server.start()

        # Start Socket Mode
        handler = AsyncSocketModeHandler(app, settings.slack_app_token)
        try:
            await handler.start_async()
        finally:
            if _webhook_server is not None:
                await _webhook_server.stop()
            if _scheduler_engine is not None:
                await _scheduler_engine.stop()

    asyncio.run(_run())
