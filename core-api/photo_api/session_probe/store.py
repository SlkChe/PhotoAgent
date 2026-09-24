"""Ограниченное RAM-хранилище эксперимента и восстановление потерянного Set-Cookie."""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


class ProbeError(Exception):
    """Безопасная ошибка экспериментального протокола."""

    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code


def digest(value: str) -> str:
    """Хеширует непрозрачный токен до размещения в RAM."""
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class Session:
    """Минимальная сессия без истории и внешних вызовов."""

    id: UUID
    token_hash: str
    activity: float
    revision: int = 1
    marker: str = ""
    opened: set[UUID] = field(default_factory=set)


@dataclass
class Context:
    """Контекст браузера с ограниченным журналом запросов создания."""

    expires: float
    epoch: str = field(default_factory=lambda: secrets.token_hex(16))
    session: Session | None = None
    creates: dict[UUID, UUID] = field(default_factory=dict)


class ProbeStore:
    """Синхронные атомарные операции одного процесса, без await внутри мутаций."""

    def __init__(self, clock: Callable[[], float], capacity: int = 1000) -> None:
        self.clock = clock
        self.capacity = capacity
        self.key = secrets.token_bytes(32)
        self.contexts: dict[str, Context] = {}

    def sign(self, value: str) -> str:
        """Получает воспроизводимый секрет из контекста и ключа процесса."""
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    def sweep(self) -> None:
        """Удаляет просроченные контексты и данные сессий."""
        now = self.clock()
        for key, context in list(self.contexts.items()):
            if context.expires <= now and (
                context.session is None or context.session.activity + 43200 <= now
            ):
                del self.contexts[key]
            elif context.session and context.session.activity + 43200 <= now:
                context.session = None

    def context(self, seed: str | None, create: bool = False) -> tuple[str, Context]:
        """Создаёт только CSRF-контекст; не создаёт и не продлевает диалог."""
        self.sweep()
        if seed and (context := self.contexts.get(digest(seed))):
            return seed, context
        if not create:
            raise ProbeError(403, "invalid_context")
        if len(self.contexts) >= self.capacity:
            raise ProbeError(503, "context_capacity")
        seed = secrets.token_urlsafe(32)
        context = Context(expires=self.clock() + 86400)
        self.contexts[digest(seed)] = context
        return seed, context

    def csrf(self, seed: str, context: Context) -> str:
        """Привязывает CSRF к cookie и поколению контекста."""
        return self.sign(f"csrf:{seed}:{context.epoch}")

    def token(self, seed: str, session: Session) -> str:
        """Восстанавливает потерянную cookie без хранения исходного bearer в RAM."""
        return self.sign(f"session:{seed}:{session.id}")

    def create(self, seed: str, context: Context, request_id: UUID) -> str:
        """Повторяет выдачу существующей cookie, не оживляя удалённую сессию."""
        previous = context.creates.get(request_id)
        if previous and (not context.session or previous != context.session.id):
            raise ProbeError(409, "creation_retired")
        if request_id not in context.creates and len(context.creates) >= 256:
            raise ProbeError(409, "request_capacity")
        if context.session is None:
            session = Session(uuid4(), "", self.clock())
            session.token_hash = digest(self.token(seed, session))
            context.session = session
        context.expires = max(context.expires, self.clock() + 86400)
        context.creates[request_id] = context.session.id
        return self.token(seed, context.session)

    def authorized(self, token: str | None, context: Context | None = None) -> Session:
        """Проверяет TTL и хеш bearer; ID сессии не является доступом."""
        self.sweep()
        candidates = [context] if context else self.contexts.values()
        for candidate in candidates:
            session = candidate.session
            if session and token and hmac.compare_digest(session.token_hash, digest(token)):
                return session
        raise ProbeError(401, "session_unavailable")

    def opened(self, session: Session, request_id: UUID) -> None:
        """Регистрирует явное открытие единожды, ограничивая RAM журнала."""
        if request_id in session.opened:
            return
        if len(session.opened) >= 1024:
            raise ProbeError(409, "request_capacity")
        session.opened.add(request_id)
        session.activity = self.clock()


def utc(timestamp: float) -> datetime:
    """Возвращает диагностическое время UTC."""
    return datetime.fromtimestamp(timestamp, UTC)
