"""MessageContext — carries channel/routing info through the request lifecycle."""

from dataclasses import dataclass, field


@dataclass
class MessageContext:
    """Context for an inbound message, used to route outbound notifications.

    Attributes:
        user_id: The user identifier (string for cross-channel compat).
        source_channel: Channel the message arrived on (e.g. 'telegram').
        reply_channel: Channel to send replies on. Defaults to source_channel.
        conversation_id: Logical conversation ID. Defaults to user_id.
        metadata: Channel-specific extras (e.g. chat_id, thread_id).
    """

    user_id: str
    source_channel: str
    reply_channel: str = ""
    conversation_id: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reply_channel:
            self.reply_channel = self.source_channel
        if not self.conversation_id:
            self.conversation_id = self.user_id
