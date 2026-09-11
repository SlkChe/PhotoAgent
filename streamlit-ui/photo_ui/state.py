"""Состояние отображения живого диалога, без записи на диск."""

from dataclasses import dataclass, field
from uuid import UUID

from shared.contracts import ChatMessage, MessageRequest


@dataclass
class ChatState:
    session_id: UUID | None = None
    messages: list[ChatMessage] = field(default_factory=list)
    pending: MessageRequest | None = None
    error: str | None = None
    expired: bool = False
