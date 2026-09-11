"""Оперативное хранилище контекста одного процесса; это не кеш ответов."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from shared.contracts import ChatMessage, MessageRequest, MessageResponse, SessionResponse, Topic

from .settings import ApiSettings
from .topics import decompose, dispatch


class SessionError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class Session:
    session_id: UUID
    expires_at: datetime
    messages: list[ChatMessage] = field(default_factory=list)
    previous_topics: list[Topic] = field(default_factory=list)
    turns: dict[UUID, tuple[str, MessageResponse]] = field(default_factory=dict)


class SessionStore:
    def __init__(
        self,
        settings: ApiSettings,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sessions: dict[UUID, Session] = {}
        self.lock = asyncio.Lock()

    def _deadline(self) -> datetime:
        return self.clock() + timedelta(seconds=self.settings.session_ttl_seconds)

    def _remove_expired(self) -> None:
        expired = [key for key, value in self.sessions.items() if value.expires_at <= self.clock()]
        for key in expired:
            del self.sessions[key]

    def _get(self, session_id: UUID) -> Session:
        self._remove_expired()
        session = self.sessions.get(session_id)
        if session is None:
            raise SessionError(404, "Сессия не найдена или уже завершена")
        return session

    def _response(self, session: Session) -> SessionResponse:
        return SessionResponse(
            session_id=session.session_id,
            expires_at=session.expires_at,
            messages=[message.model_copy() for message in session.messages],
        )

    async def create(self) -> SessionResponse:
        async with self.lock:
            self._remove_expired()
            if len(self.sessions) >= self.settings.max_sessions:
                raise SessionError(503, "Достигнут лимит сессий. Попробуйте позже")
            session = Session(session_id=uuid4(), expires_at=self._deadline())
            self.sessions[session.session_id] = session
            return self._response(session)

    async def get(self, session_id: UUID) -> SessionResponse:
        async with self.lock:
            return self._response(self._get(session_id))

    async def touch(self, session_id: UUID) -> datetime:
        async with self.lock:
            session = self._get(session_id)
            session.expires_at = self._deadline()
            return session.expires_at

    async def delete(self, session_id: UUID) -> None:
        async with self.lock:
            self.sessions.pop(session_id, None)

    async def send(self, session_id: UUID, request: MessageRequest) -> MessageResponse:
        async with self.lock:
            session = self._get(session_id)
            if request.request_id in session.turns:
                previous_text, response = session.turns[request.request_id]
                if previous_text != request.text:
                    raise SessionError(
                        409, "Идентификатор отправки уже использован для другой реплики"
                    )
                session.expires_at = self._deadline()
                return response.model_copy(deep=True)
            if len(session.turns) >= self.settings.max_turns:
                raise SessionError(409, "Достигнут лимит реплик. Начните новый чат")
            topics = decompose(request.text, session.previous_topics)
            response = MessageResponse(
                request_id=request.request_id,
                topics=topics,
                reply=dispatch(topics),
            )
            session.messages.extend(
                [
                    ChatMessage(role="user", text=request.text),
                    ChatMessage(role="assistant", text=response.reply),
                ]
            )
            context_topics = [topic for topic in topics if topic != Topic.CONFIRMATION]
            if context_topics:
                session.previous_topics = context_topics
            session.turns[request.request_id] = (request.text, response)
            session.expires_at = self._deadline()
            return response.model_copy(deep=True)

    async def sweep(self) -> None:
        async with self.lock:
            self._remove_expired()

    async def clear(self) -> None:
        async with self.lock:
            self.sessions.clear()
