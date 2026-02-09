"""Claude API client for generating responses."""

import logging

import anthropic

from src.config import settings
from src.llm.prompt import build_system_prompt
from src.memory.store import get_recent_messages

logger = logging.getLogger(__name__)

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def generate_response(user_message: str, chat_id: str) -> str:
    """Generate a response using Claude.

    Args:
        user_message: The user's message text.
        chat_id: The Telegram chat ID for conversation context.

    Returns:
        The assistant's response text.
    """
    system_prompt = await build_system_prompt()
    history = await get_recent_messages(chat_id=chat_id, limit=50)

    messages = [
        {"role": msg.role, "content": msg.content}
        for msg in history
    ]
    messages.append({"role": "user", "content": user_message})

    try:
        response = await _client.messages.create(
            model=settings.claude_model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text
    except anthropic.APIError:
        logger.exception("Claude API error")
        return "I hit an issue talking to my brain. Try again in a moment."
