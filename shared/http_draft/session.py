"""Кандидат snapshot и восстановления B-01, с предметным Answer версии 1.1."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from shared.mvp_contracts.answer import Answer
from shared.mvp_contracts.common import ContractModel, Revision, Text, UtcDatetime
from shared.mvp_contracts.evidence import AnswerSource

from .operations import AnswerState, DraftEnvelope, RoleRef, SettingsValue

type Stage = Literal[
    "queued",
    "analyzing",
    "searching",
    "building_evidence",
    "generating",
    "validating",
    "completed",
    "failed",
    "cancelled",
]


class DraftExecutionError(ContractModel):
    code: Literal[
        "provider_error",
        "deadline_exceeded",
        "invalid_output",
        "internal_error",
        "budget_exhausted",
    ] = Field(
        description="budget_exhausted — предлагаемое дополнение, не изменение 1.1",
        examples=["budget_exhausted"],
    )
    message: Text = Field(
        description="Без промптов и сырых ошибок провайдера", examples=["Бюджет генерации исчерпан"]
    )
    retryable: StrictBool = Field(
        description="Допустима новая явная попытка, не автоматический retry", examples=[False]
    )


class ExecutionSummary(ContractModel):
    request_id: UUID = Field(
        description="ID исходной отправки", examples=["22222222-2222-4222-8222-222222222222"]
    )
    execution_id: UUID = Field(
        description="ID выполнения", examples=["33333333-3333-4333-8333-333333333333"]
    )
    status: Stage = Field(description="Безопасная стадия для UI", examples=["completed"])
    answer_id: UUID | None = Field(description="Ответ только для completed", examples=[None])
    error: DraftExecutionError | None = Field(
        description="Ошибка только для failed", examples=[None]
    )

    @model_validator(mode="after")
    def terminal(self) -> Self:
        if (self.status == "completed") != (self.answer_id is not None):
            raise ValueError("answer_id требуется только для completed")
        if (self.status == "failed") != (self.error is not None):
            raise ValueError("error требуется только для failed")
        return self


class ExecutionView(DraftEnvelope):
    session_id: UUID = Field(
        description="Авторизованный владелец выполнения",
        examples=["11111111-1111-4111-8111-111111111111"],
    )
    execution: ExecutionSummary = Field(description="Стадия и идентичность отправки")
    answer: Answer | None = Field(
        description="Предметный Answer 1.1 только для completed", examples=[None]
    )
    author: RoleRef | None = Field(
        description="Неизменная подпись ответа; только при наличии Answer", examples=[None]
    )

    @model_validator(mode="after")
    def identity(self) -> Self:
        if (self.execution.status == "completed") != (self.answer is not None):
            raise ValueError("Ответ только для completed")
        if (self.answer is None) != (self.author is None):
            raise ValueError("Ответ и подпись должны присутствовать вместе")
        if self.answer and (
            self.answer.session_id != self.session_id
            or self.answer.request_id != self.execution.request_id
            or self.answer.execution_id != self.execution.execution_id
            or self.answer.answer_id != self.execution.answer_id
        ):
            raise ValueError("Идентичность ответа отличается от выполнения")
        return self


class UserMessage(ContractModel):
    kind: Literal["user"] = Field(
        description="Роль сообщения, не специализация ассистента", examples=["user"]
    )
    message_id: UUID = Field(
        description="ID сообщения для восстановления порядка",
        examples=["44444444-4444-4444-8444-444444444444"],
    )
    created_at: UtcDatetime = Field(
        description="Время принятия реплики UTC", examples=["2026-09-24T10:00:00Z"]
    )
    request_id: UUID = Field(
        description="Для восстановления принятой отправки после потери ответа",
        examples=["22222222-2222-4222-8222-222222222222"],
    )
    execution_id: UUID = Field(
        description="Связанное выполнение", examples=["33333333-3333-4333-8333-333333333333"]
    )
    text: Text = Field(
        description="Исходная реплика без перевода", examples=["Что такое диафрагма?"]
    )
    settings: SettingsValue = Field(description="Настройки принятой отправки")


class AssistantMessage(ContractModel):
    kind: Literal["assistant"] = Field(
        description="Роль сообщения в диалоге", examples=["assistant"]
    )
    message_id: UUID = Field(
        description="ID сообщения", examples=["55555555-5555-4555-8555-555555555555"]
    )
    created_at: UtcDatetime = Field(
        description="Время публикации проверенного ответа UTC", examples=["2026-09-24T10:00:01Z"]
    )
    author: RoleRef = Field(description="Подпись на момент публикации, не текущая роль")
    answer: Answer = Field(description="Полный публичный Answer 1.1")


type HistoryMessage = Annotated[UserMessage | AssistantMessage, Field(discriminator="kind")]


class SourceCard(ContractModel):
    card_id: UUID = Field(
        description="ID карточки точного URL в этой сессии",
        examples=["77777777-7777-4777-8777-777777777777"],
    )
    source: AnswerSource = Field(description="Публичные метаданные первого появления URL")
    first_answer_id: UUID = Field(
        description="Переход к первому ответу", examples=["66666666-6666-4666-8666-666666666666"]
    )
    first_message_id: UUID = Field(
        description="ID сообщения первого ответа", examples=["55555555-5555-4555-8555-555555555555"]
    )
    context_comment: Text = Field(
        description="Исходная реплика первого запроса, без новой генерации",
        examples=["Что такое диафрагма?"],
    )


class PendingClarification(ContractModel):
    answer_id: UUID = Field(
        description="Ответ с вопросом-уточнением", examples=["66666666-6666-4666-8666-666666666666"]
    )
    clarification_id: Text = Field(
        description="ID уточнения из Answer", examples=["clarification-1"]
    )
    question: Text = Field(
        description="Текст для восстановления UI", examples=["Какую камеру вы имеете в виду?"]
    )
    options: list[str] = Field(description="Подсказки; свободный ответ допустим", examples=[[]])


class Capabilities(ContractModel):
    max_message_chars: Annotated[int, Field(strict=True, gt=0)] = Field(
        description="Фактический предел конфигурации, не новое фиксированное требование",
        examples=[4000],
    )
    max_feedback_comment_chars: Annotated[int, Field(strict=True, gt=0)] = Field(
        description="Фактический предел комментария", examples=[1000]
    )
    can_export_dialogue: StrictBool = Field(
        description="Есть реплики для экспорта", examples=[True]
    )
    can_export_sources: StrictBool = Field(
        description="Есть источники для экспорта", examples=[True]
    )


class SessionSnapshot(DraftEnvelope):
    session_id: UUID = Field(
        description="ID для сравнения вкладок, не авторизация",
        examples=["11111111-1111-4111-8111-111111111111"],
    )
    revision: Revision = Field(description="Версия всего публичного состояния", examples=[3])
    last_activity_at: UtcDatetime = Field(
        description="Только согласованные явные действия", examples=["2026-09-24T10:00:00Z"]
    )
    expires_at: UtcDatetime = Field(
        description="Ровно last_activity_at + 43200 секунд", examples=["2026-09-24T22:00:00Z"]
    )
    settings_revision: Revision = Field(description="Отдельная версия настроек", examples=[0])
    settings: SettingsValue = Field(description="Настройки будущих отправок")
    current_role: RoleRef = Field(description="Текущая роль; не переподписывает историю")
    session_status: Literal["ready", "in_progress", "awaiting_clarification"] = Field(
        description="Состояние живой сессии", examples=["ready"]
    )
    active_execution_id: UUID | None = Field(
        description="Непустой только при in_progress", examples=[None]
    )
    pending_clarification: PendingClarification | None = Field(
        description="Только при awaiting_clarification", examples=[None]
    )
    messages: list[HistoryMessage] = Field(
        description="Полная упорядоченная история в пределах лимита сессии"
    )
    executions: list[ExecutionSummary] = Field(
        description="Состояния всех принятых запросов, включая ошибки"
    )
    source_cards: list[SourceCard] = Field(
        description="Уникальные точные URL в порядке первого появления", examples=[[]]
    )
    answer_states: list[AnswerState] = Field(
        description="Восстановление отметок показа и оценки", examples=[[]]
    )
    capabilities: Capabilities = Field(description="Ограничения и доступность экспорта")

    @model_validator(mode="after")
    def state(self) -> Self:
        from .validation import validate_snapshot

        validate_snapshot(self)
        return self
