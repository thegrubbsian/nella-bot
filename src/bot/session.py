"""In-memory conversation session with sliding window."""

import logging
from dataclasses import dataclass, field

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A single conversation turn."""

    role: str  # "user" or "assistant"
    content: str


@dataclass
class Session:
    """Conversation history for a single chat."""

    messages: list[Message] = field(default_factory=list)
    window_size: int = field(default_factory=lambda: settings.conversation_window_size)

    def add(self, role: str, content: str) -> None:
        """Append a message and trim to the sliding window."""
        self.messages.append(Message(role=role, content=content))
        if len(self.messages) > self.window_size:
            self.messages = self.messages[-self.window_size :]

    def clear(self) -> int:
        """Clear all messages. Returns the count of cleared messages."""
        count = len(self.messages)
        self.messages.clear()
        return count

    def to_api_messages(self) -> list[dict[str, str]]:
        """Format messages for the Claude API."""
        return [{"role": m.role, "content": m.content} for m in self.messages]


# Global session store keyed by session ID (str(chat_id) for Telegram, phone for SMS)
_sessions: dict[str, Session] = {}


def get_session(session_id: str) -> Session:
    """Get or create a session for a chat."""
    if session_id not in _sessions:
        _sessions[session_id] = Session()
    return _sessions[session_id]
