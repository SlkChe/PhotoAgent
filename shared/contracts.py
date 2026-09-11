"""Модели запросов и ответов прототипа."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Topic(StrEnum):
    CONFIRMATION = "confirmation"
    SEARCH = "search"
    THEORY = "theory"
    FRAME = "frame"


TOPIC_LABELS: dict[Topic, str] = {
    Topic.CONFIRMATION: "Утвердительный ответ",
    Topic.SEARCH: "Поиск оборудования или услуг",
    Topic.THEORY: "Теоретические вопросы",
    Topic.FRAME: "Вопросы к конкретным кадрам",
}


class MessageRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    request_id: UUID = Field(
        description="Идентификатор отправки для защиты от повторной обработки",
        examples=["d8279971-1270-4d07-bda9-6d94cbe5b242"],
    )
    text: str = Field(
        min_length=1,
        max_length=4000,
        description="Реплика пользователя",
        examples=["Объясни глубину резкости"],
    )


class MessageResponse(BaseModel):
    request_id: UUID = Field(
        description="Идентификатор отправки",
        examples=["d8279971-1270-4d07-bda9-6d94cbe5b242"],
    )
    topics: list[Topic] = Field(
        description="Выделенные темы в порядке обработки",
        examples=[["theory"]],
    )
    reply: str = Field(
        description="Названия тем от обработчиков-заглушек",
        examples=["Теоретические вопросы"],
    )


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$", description="Автор реплики", examples=["user"])
    text: str = Field(description="Текст реплики", examples=["Объясни глубину резкости"])


class SessionResponse(BaseModel):
    session_id: UUID = Field(
        description="Случайный идентификатор доступа к сессии",
        examples=["89c464d8-c003-4417-8a7c-4b067c26bff9"],
    )
    expires_at: datetime = Field(
        description="Срок жизни сессии без продления",
        examples=["2026-09-11T12:03:00Z"],
    )
    messages: list[ChatMessage] = Field(description="Реплики текущего диалога", examples=[[]])


class LeaseResponse(BaseModel):
    expires_at: datetime = Field(
        description="Новый срок жизни сессии",
        examples=["2026-09-11T12:03:20Z"],
    )


class ErrorResponse(BaseModel):
    detail: str = Field(description="Описание ошибки", examples=["Сессия не найдена"])


class HealthResponse(BaseModel):
    status: str = Field(description="Состояние сервиса", examples=["ok"])
