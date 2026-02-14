"""Parse slack_manifest.yaml to extract OAuth scopes."""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_MANIFEST_PATH = Path(__file__).resolve().parent.parent.parent.parent / "slack_manifest.yaml"


def get_slack_scopes() -> list[str]:
    """Read slack_manifest.yaml and return a sorted, deduplicated list of all OAuth scopes."""
    if not _MANIFEST_PATH.exists():
        logger.warning("slack_manifest.yaml not found at %s", _MANIFEST_PATH)
        return []

    try:
        data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
        scopes_cfg = data.get("oauth_config", {}).get("scopes", {})
        bot_scopes: list[str] = scopes_cfg.get("bot", []) or []
        user_scopes: list[str] = scopes_cfg.get("user", []) or []
        return sorted(set(bot_scopes + user_scopes))
    except Exception:
        logger.exception("Failed to parse slack_manifest.yaml")
        return []
