"""Проверка связности примеров HTTP-кандидата; не авторизация runtime."""

from typing import TYPE_CHECKING
from uuid import UUID

from shared.mvp_contracts.common import unique
from shared.mvp_contracts.evidence import AnswerSource

from .session import AssistantMessage, UserMessage

if TYPE_CHECKING:
    from .session import SessionSnapshot


def validate_snapshot(snapshot: SessionSnapshot) -> None:
    """Проверяет роли, состояние, принадлежность и ссылки восстановленного диалога."""
    if (snapshot.expires_at - snapshot.last_activity_at).total_seconds() != 43200:
        raise ValueError("Нарушена граница TTL")
    if (snapshot.session_status == "in_progress") != (snapshot.active_execution_id is not None):
        raise ValueError("Активное выполнение не соответствует статусу")
    if (snapshot.session_status == "awaiting_clarification") != (
        snapshot.pending_clarification is not None
    ):
        raise ValueError("Уточнение не соответствует статусу")
    unique([str(m.message_id) for m in snapshot.messages], "messages")
    unique([str(e.execution_id) for e in snapshot.executions], "executions")
    unique([str(e.request_id) for e in snapshot.executions], "requests")
    execution_map = {e.execution_id: e for e in snapshot.executions}
    active = [
        e.execution_id
        for e in snapshot.executions
        if e.status not in ("completed", "failed", "cancelled")
    ]
    if active != ([] if snapshot.active_execution_id is None else [snapshot.active_execution_id]):
        raise ValueError("Список активных выполнений не совпадает со снимком")
    users = {m.execution_id: m for m in snapshot.messages if isinstance(m, UserMessage)}
    if len(users) != sum(isinstance(m, UserMessage) for m in snapshot.messages):
        raise ValueError("Повтор реплики выполнения")
    if set(users) != set(execution_map):
        raise ValueError("Принятые реплики и выполнения не совпадают")
    for key, message in users.items():
        if message.request_id != execution_map[key].request_id:
            raise ValueError("ID отправки отличается")
    answers = [m for m in snapshot.messages if isinstance(m, AssistantMessage)]
    validate_answers(snapshot, answers, users)


def validate_answers(
    snapshot: SessionSnapshot, answers: list[AssistantMessage], users: dict[UUID, UserMessage]
) -> None:
    """Проверяет ответы, их оценки, неизменную первичную привязку источников."""
    unique([str(m.answer.answer_id) for m in answers], "answers")
    completed = {e.execution_id: e for e in snapshot.executions if e.status == "completed"}
    if len(answers) != len(completed) or {m.answer.execution_id for m in answers} != set(completed):
        raise ValueError("Ответы не соответствуют завершённым выполнениям")
    for message in answers:
        answer = message.answer
        execution = completed[answer.execution_id]
        if (
            answer.session_id != snapshot.session_id
            or answer.answer_id != execution.answer_id
            or answer.request_id != execution.request_id
        ):
            raise ValueError("Чужой или несогласованный ответ")
        source_message = users[answer.execution_id]
        if (
            answer.locale != source_message.settings.locale
            or answer.style.model_dump() != source_message.settings.model_dump(exclude={"locale"})
        ):
            raise ValueError("Настройки ответа не совпадают с принятой репликой")
    by_id = {m.answer.answer_id: m for m in answers}
    unique([str(s.answer_id) for s in snapshot.answer_states], "answer_states")
    if {s.answer_id for s in snapshot.answer_states} != set(by_id):
        raise ValueError("Не все состояния ответов восстановлены")
    for state in snapshot.answer_states:
        if state.eligible != (
            by_id[state.answer_id].answer.kind in ("answer", "insufficient_evidence")
        ):
            raise ValueError("Неверная применимость оценки")
    if pending := snapshot.pending_clarification:
        if pending.answer_id not in by_id:
            raise ValueError("Уточнение неизвестного ответа")
        clarification = by_id[pending.answer_id].answer.clarification
        if clarification is None or (
            clarification.id,
            clarification.question,
            clarification.options,
        ) != (pending.clarification_id, pending.question, pending.options):
            raise ValueError("Уточнение не соответствует Answer")
    validate_cards(snapshot, answers, users)


def validate_cards(
    snapshot: SessionSnapshot, answers: list[AssistantMessage], users: dict[UUID, UserMessage]
) -> None:
    """Точный URL определяет одну карточку с первым ответом и его исходной репликой."""
    unique([str(c.card_id) for c in snapshot.source_cards], "cards")
    unique([c.source.url for c in snapshot.source_cards], "card URLs")
    first: dict[str, tuple[AssistantMessage, AnswerSource]] = {}
    for message in answers:
        for source in message.answer.sources:
            first.setdefault(source.url, (message, source))
    if list(first) != [card.source.url for card in snapshot.source_cards]:
        raise ValueError("Карточки не следуют первому появлению URL")
    for card in snapshot.source_cards:
        message, source = first[card.source.url]
        if (
            card.first_answer_id != message.answer.answer_id
            or card.first_message_id != message.message_id
            or card.source != source
        ):
            raise ValueError("Изменена первичная привязка карточки")
        if card.context_comment != users[message.answer.execution_id].text:
            raise ValueError("Контекст карточки не совпадает с первой репликой")
