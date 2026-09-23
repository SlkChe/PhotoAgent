"""Общие типы предметных контрактов MVP-1; не модели прототипа."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
)


def nonblank(value: str) -> str:
    """Проверяет содержательность, сохраняя исходный текст и точный URL."""
    if not value.strip():
        raise ValueError("Строка не должна быть пустой")
    return value


def utc_datetime(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("Требуется время UTC")
    return value.astimezone(UTC)


def http_url(value: str) -> str:
    parsed = TypeAdapter(HttpUrl).validate_python(value)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL не должен содержать учётные данные")
    if value != value.strip() or any(ord(char) <= 32 for char in value):
        raise ValueError("URL содержит пробельные или управляющие символы")
    return value


type Text = Annotated[str, Field(min_length=1), AfterValidator(nonblank)]
type UtcDatetime = Annotated[AwareDatetime, AfterValidator(utc_datetime)]
type WebUrl = Annotated[Text, AfterValidator(http_url)]
type PositiveInt = Annotated[int, Field(strict=True, gt=0)]
type Revision = Annotated[int, Field(strict=True, ge=0)]
type Locale = Literal["ru"]
type Topic = Literal["technology", "art", "actors", "genres", "works"]
type Intent = Literal[
    "reference",
    "explain",
    "historical_overview",
    "timeline",
    "compare",
    "fact_check",
    "artistic_significance",
    "source_selection",
]
type Operation = Literal["search", "fetch", "entity_lookup"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ExecutionIdentity(ContractModel):
    session_id: UUID = Field(
        description="Владелец выполнения", examples=["11111111-1111-4111-8111-111111111111"]
    )
    request_id: UUID = Field(
        description="Ключ отправки клиента", examples=["22222222-2222-4222-8222-222222222222"]
    )
    execution_id: UUID = Field(
        description="Выполнение, назначенное API", examples=["33333333-3333-4333-8333-333333333333"]
    )


class Envelope(ExecutionIdentity):
    schema_version: Literal["1.1"] = Field(description="Версия предметной схемы", examples=["1.1"])


def unique(values: list[str], label: str) -> set[str]:
    result = set(values)
    if len(result) != len(values):
        raise ValueError(f"Повтор идентификатора: {label}")
    return result


def references(values: list[str], available: set[str], label: str) -> None:
    if not unique(values, label) <= available:
        raise ValueError(f"Неизвестная ссылка: {label}")
