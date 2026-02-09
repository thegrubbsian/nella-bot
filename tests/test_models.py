"""Tests for model manager."""

from unittest.mock import patch

from src.llm.models import MODEL_MAP, ModelManager, friendly


@patch("src.llm.models.settings")
def test_default_models(mock_settings) -> None:
    mock_settings.default_chat_model = "sonnet"
    mock_settings.default_memory_model = "haiku"
    ModelManager._instance = None
    mm = ModelManager.get()
    assert mm.get_chat_model() == MODEL_MAP["sonnet"]
    assert mm.get_memory_model() == MODEL_MAP["haiku"]
    ModelManager._instance = None


@patch("src.llm.models.settings")
def test_set_chat_model_by_name(mock_settings) -> None:
    mock_settings.default_chat_model = "sonnet"
    mock_settings.default_memory_model = "haiku"
    ModelManager._instance = None
    mm = ModelManager.get()
    result = mm.set_chat_model("opus")
    assert result == MODEL_MAP["opus"]
    assert mm.get_chat_model() == MODEL_MAP["opus"]
    # Memory model should be unchanged
    assert mm.get_memory_model() == MODEL_MAP["haiku"]
    ModelManager._instance = None


@patch("src.llm.models.settings")
def test_set_chat_model_invalid(mock_settings) -> None:
    mock_settings.default_chat_model = "sonnet"
    mock_settings.default_memory_model = "haiku"
    ModelManager._instance = None
    mm = ModelManager.get()
    result = mm.set_chat_model("gpt-4")
    assert result is None
    assert mm.get_chat_model() == MODEL_MAP["sonnet"]
    ModelManager._instance = None


@patch("src.llm.models.settings")
def test_set_memory_model(mock_settings) -> None:
    mock_settings.default_chat_model = "sonnet"
    mock_settings.default_memory_model = "haiku"
    ModelManager._instance = None
    mm = ModelManager.get()
    result = mm.set_memory_model("sonnet")
    assert result == MODEL_MAP["sonnet"]
    assert mm.get_memory_model() == MODEL_MAP["sonnet"]
    ModelManager._instance = None


@patch("src.llm.models.settings")
def test_env_defaults_respected(mock_settings) -> None:
    mock_settings.default_chat_model = "opus"
    mock_settings.default_memory_model = "sonnet"
    ModelManager._instance = None
    mm = ModelManager.get()
    assert mm.get_chat_model() == MODEL_MAP["opus"]
    assert mm.get_memory_model() == MODEL_MAP["sonnet"]
    ModelManager._instance = None


def test_friendly_name() -> None:
    assert friendly(MODEL_MAP["sonnet"]) == "sonnet"
    assert friendly(MODEL_MAP["haiku"]) == "haiku"
    assert friendly(MODEL_MAP["opus"]) == "opus"
    assert friendly("unknown-model") == "unknown-model"


@patch("src.llm.models.settings")
def test_set_by_full_model_id(mock_settings) -> None:
    mock_settings.default_chat_model = "sonnet"
    mock_settings.default_memory_model = "haiku"
    ModelManager._instance = None
    mm = ModelManager.get()
    result = mm.set_chat_model("claude-opus-4-6-20250612")
    assert result == MODEL_MAP["opus"]
    assert mm.get_chat_model() == MODEL_MAP["opus"]
    ModelManager._instance = None
