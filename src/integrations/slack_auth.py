"""Slack authentication manager — multi-workspace registry."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SlackWorkspaceConfig:
    """Token bundle for a single Slack workspace."""

    bot_token: str
    user_token: str
    signing_secret: str
    team_id: str
    bot_user_id: str


class SlackAuthManager:
    """Per-workspace Slack credentials and API client builder.

    Instances are cached by workspace name. Use ``get(workspace)`` to obtain
    the manager for a named workspace (or the default).
    """

    _instances: dict[str, SlackAuthManager] = {}

    def __init__(self, workspace: str, token_path: Path) -> None:
        self._workspace = workspace
        self._token_path = token_path
        self._config: SlackWorkspaceConfig | None = None
        self._bot_client_cache = None
        self._user_client_cache = None

    # -- class-level lookups --------------------------------------------------

    @classmethod
    def get(cls, workspace: str | None = None) -> SlackAuthManager:
        """Return the manager for *workspace*, creating it lazily.

        When *workspace* is ``None``, the default workspace from settings is used.
        Raises ``ValueError`` if the workspace is not in ``SLACK_WORKSPACES``.
        """
        configured = settings.get_slack_workspaces()
        if not configured:
            msg = (
                "SLACK_WORKSPACES is not configured. "
                "Set it in .env (e.g. SLACK_WORKSPACES=personal,work)."
            )
            raise ValueError(msg)

        name = workspace or settings.slack_default_workspace
        if not name:
            name = configured[0]

        if name not in configured:
            msg = (
                f"Slack workspace '{name}' is not in SLACK_WORKSPACES "
                f"({', '.join(configured)})"
            )
            raise ValueError(msg)

        if name not in cls._instances:
            token_path = Path(f"auth_tokens/slack_{name}.json")
            cls._instances[name] = cls(name, token_path)

        return cls._instances[name]

    @classmethod
    def any_enabled(cls) -> bool:
        """True if any configured workspace has a token file on disk."""
        configured = settings.get_slack_workspaces()
        if not configured:
            return False
        return any(
            Path(f"auth_tokens/slack_{name}.json").exists() for name in configured
        )

    @classmethod
    def get_by_team_id(cls, team_id: str) -> SlackAuthManager | None:
        """Find the manager whose config matches *team_id*.

        Loads configs lazily for all configured workspaces to find the match.
        Returns ``None`` if no workspace matches.
        """
        configured = settings.get_slack_workspaces()
        for name in configured:
            try:
                mgr = cls.get(name)
                cfg = mgr._load_config()
                if cfg.team_id == team_id:
                    return mgr
            except (FileNotFoundError, ValueError):
                continue
        return None

    @classmethod
    def _reset(cls) -> None:
        """Clear cached instances (for testing)."""
        cls._instances.clear()

    # -- config loading -------------------------------------------------------

    def _load_config(self) -> SlackWorkspaceConfig:
        """Load workspace config from the JSON token file."""
        if self._config is not None:
            return self._config

        if not self._token_path.exists():
            msg = (
                f"Slack token file not found at {self._token_path}. "
                f"Create it with bot_token, user_token, signing_secret, team_id, "
                f"and bot_user_id fields."
            )
            raise FileNotFoundError(msg)

        data = json.loads(self._token_path.read_text(encoding="utf-8"))
        self._config = SlackWorkspaceConfig(
            bot_token=data["bot_token"],
            user_token=data["user_token"],
            signing_secret=data["signing_secret"],
            team_id=data["team_id"],
            bot_user_id=data["bot_user_id"],
        )
        return self._config

    # -- properties -----------------------------------------------------------

    @property
    def workspace(self) -> str:
        return self._workspace

    @property
    def signing_secret(self) -> str:
        return self._load_config().signing_secret

    @property
    def bot_user_id(self) -> str:
        return self._load_config().bot_user_id

    @property
    def team_id(self) -> str:
        return self._load_config().team_id

    # -- client builders ------------------------------------------------------

    def bot_client(self):
        """Return an AsyncWebClient configured with the bot token."""
        if self._bot_client_cache is None:
            from slack_sdk.web.async_client import AsyncWebClient

            self._bot_client_cache = AsyncWebClient(token=self._load_config().bot_token)
        return self._bot_client_cache

    def user_client(self):
        """Return an AsyncWebClient configured with the user token."""
        if self._user_client_cache is None:
            from slack_sdk.web.async_client import AsyncWebClient

            self._user_client_cache = AsyncWebClient(token=self._load_config().user_token)
        return self._user_client_cache
