"""Tests for complete_text() bare LLM call."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.llm.client import complete_text


async def test_complete_text_basic() -> None:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="hello world")]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    mock_model_mgr = MagicMock()
    mock_model_mgr.get_chat_model.return_value = "claude-test-model"

    with (
        patch("src.llm.client._get_client", return_value=mock_client),
        patch("src.llm.models.ModelManager.get", return_value=mock_model_mgr),
    ):
        result = await complete_text([{"role": "user", "content": "hi"}])

    assert result == "hello world"
    mock_client.messages.create.assert_awaited_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert call_kwargs["model"] == "claude-test-model"
    assert call_kwargs["max_tokens"] == 4096


async def test_complete_text_with_system() -> None:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="response")]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    mock_model_mgr = MagicMock()
    mock_model_mgr.get_chat_model.return_value = "claude-test-model"

    with (
        patch("src.llm.client._get_client", return_value=mock_client),
        patch("src.llm.models.ModelManager.get", return_value=mock_model_mgr),
    ):
        result = await complete_text(
            [{"role": "user", "content": "hi"}],
            system="You are helpful.",
        )

    assert result == "response"
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["system"] == "You are helpful."


async def test_complete_text_with_custom_model() -> None:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="response")]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("src.llm.client._get_client", return_value=mock_client):
        await complete_text(
            [{"role": "user", "content": "hi"}],
            model="claude-haiku-4-5-20251001",
        )

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"


async def test_complete_text_omits_system_when_none() -> None:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="response")]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    mock_model_mgr = MagicMock()
    mock_model_mgr.get_chat_model.return_value = "claude-test-model"

    with (
        patch("src.llm.client._get_client", return_value=mock_client),
        patch("src.llm.models.ModelManager.get", return_value=mock_model_mgr),
    ):
        await complete_text([{"role": "user", "content": "hi"}])

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert "system" not in call_kwargs
