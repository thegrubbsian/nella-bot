"""Model manager for runtime model switching."""

import logging

from src.config import settings

logger = logging.getLogger(__name__)

MODEL_MAP: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-6-20250612",
}

# Reverse lookup: full model string → friendly name
FRIENDLY_NAMES: dict[str, str] = {v: k for k, v in MODEL_MAP.items()}


def _resolve(name_or_id: str) -> str | None:
    """Resolve a friendly name or full model ID. Returns full ID or None."""
    if name_or_id in MODEL_MAP:
        return MODEL_MAP[name_or_id]
    if name_or_id in FRIENDLY_NAMES:
        return name_or_id
    return None


def friendly(model_id: str) -> str:
    """Return the friendly name for a model ID, or the ID itself."""
    return FRIENDLY_NAMES.get(model_id, model_id)


class ModelManager:
    """Singleton that tracks which models are active for chat and memory."""

    _instance: "ModelManager | None" = None

    def __init__(self) -> None:
        self._chat_model = _resolve(settings.default_chat_model) or MODEL_MAP["sonnet"]
        self._memory_model = _resolve(settings.default_memory_model) or MODEL_MAP["haiku"]
        logger.info(
            "Models: chat=%s, memory=%s",
            friendly(self._chat_model),
            friendly(self._memory_model),
        )

    @classmethod
    def get(cls) -> "ModelManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_chat_model(self) -> str:
        return self._chat_model

    def get_memory_model(self) -> str:
        return self._memory_model

    def set_chat_model(self, name: str) -> str | None:
        """Set chat model by friendly name. Returns full ID or None if invalid."""
        model_id = _resolve(name)
        if model_id:
            self._chat_model = model_id
            logger.info("Chat model → %s", friendly(model_id))
        return model_id

    def set_memory_model(self, name: str) -> str | None:
        """Set memory model by friendly name. Returns full ID or None if invalid."""
        model_id = _resolve(name)
        if model_id:
            self._memory_model = model_id
            logger.info("Memory model → %s", friendly(model_id))
        return model_id
