"""Утверждённые конверты принятия, результата и ошибки выполнения."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from .answer import Answer
from .common import ContractModel, Envelope, ExecutionIdentity, Text


class ExecutionAccepted(ExecutionIdentity):
    session_status: Literal["in_progress"] = Field(
        description="Состояние в момент принятия", examples=["in_progress"]
    )


class ExecutionError(ContractModel):
    code: Literal["provider_error", "deadline_exceeded", "invalid_output", "internal_error"] = (
        Field(description="Безопасная причина ошибки", examples=["provider_error"])
    )
    message: Text = Field(
        description="Сообщение без сырой ошибки провайдера", examples=["Сервис временно недоступен"]
    )
    retryable: StrictBool = Field(description="Допустимость новой явной попытки", examples=[True])


class ExecutionResult(Envelope):
    status: Literal[
        "queued",
        "analyzing",
        "searching",
        "building_evidence",
        "generating",
        "validating",
        "completed",
        "failed",
        "cancelled",
    ] = Field(description="Стадия выполнения", examples=["queued"])
    answer: Answer | None = Field(
        description="Только проверенный завершённый ответ", examples=[None]
    )
    error: ExecutionError | None = Field(description="Только для failed", examples=[None])

    @model_validator(mode="after")
    def terminal_payload(self) -> Self:
        if (self.status == "completed") != (self.answer is not None):
            raise ValueError("Answer разрешён только при completed")
        if (self.status == "failed") != (self.error is not None):
            raise ValueError("Ошибка разрешена только при failed")
        if self.answer and any(
            getattr(self, key) != getattr(self.answer, key)
            for key in ("session_id", "request_id", "execution_id")
        ):
            raise ValueError("Ответ принадлежит другому выполнению")
        return self


class ApiError(ContractModel):
    schema_version: Literal["1.1"] = Field(description="Версия ошибки", examples=["1.1"])
    code: Text = Field(
        description="Безопасный код из контракта маршрута", examples=["session_busy"]
    )
    message: Text = Field(
        description="Публичное сообщение без секретов", examples=["Запрос обрабатывается"]
    )
    session_id: UUID | None = Field(description="Только авторизованная сессия", examples=[None])
    request_id: UUID | None = Field(description="ID отправки, если доступен", examples=[None])
    session_status: Literal["ready", "in_progress", "awaiting_clarification", "closed"] | None = (
        Field(description="Состояние доступной сессии", examples=[None])
    )
    active_execution_id: UUID | None = Field(
        description="Доступное активное выполнение", examples=[None]
    )

    @model_validator(mode="after")
    def busy_state(self) -> Self:
        if self.code == "session_busy":
            if self.session_status != "in_progress" or self.active_execution_id is None:
                raise ValueError("session_busy требует активного выполнения")
        return self
