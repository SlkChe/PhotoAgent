"""Локальный анализ вопроса и предлагаемое изменение контекста."""

from typing import Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator

from .common import (
    ContractModel,
    Envelope,
    Intent,
    Locale,
    Revision,
    Text,
    Topic,
    references,
    unique,
)


class Entity(ContractModel):
    entity_id: Text = Field(description="ID сущности в контексте", examples=["author-1"])
    kind: Literal["person", "organization", "work", "technology", "movement", "genre", "place"] = (
        Field(description="Тип сущности", examples=["person"])
    )
    label: Text = Field(description="Название сущности", examples=["Автор"])
    aliases: list[str] = Field(description="Известные варианты имени", examples=[[]])
    external_id: str | None = Field(description="ID внешнего справочника", examples=[None])


class TimeScope(ContractModel):
    label: Text = Field(description="Исходная временная оговорка", examples=["начало XX века"])
    start_year: StrictInt | None = Field(description="Нижняя граница года", examples=[1900])
    end_year: StrictInt | None = Field(description="Верхняя граница года", examples=[1910])

    @model_validator(mode="after")
    def ordered_years(self) -> Self:
        if self.start_year is not None and self.end_year is not None:
            if self.start_year > self.end_year:
                raise ValueError("Начало периода позже конца")
        return self


class Subquestion(ContractModel):
    id: Text = Field(description="ID подвопроса", examples=["q1"])
    text: Text = Field(
        description="Допустимая содержательная часть вопроса", examples=["Когда создана серия?"]
    )
    intent: Intent = Field(description="Задача подвопроса", examples=["reference"])
    topics: list[Topic] = Field(description="Предметные тематики", examples=[["works"]])
    entity_ids: list[Text] = Field(
        description="Сущности анализа или текущей сессии", examples=[["work-1"]]
    )

    @model_validator(mode="after")
    def unique_topics(self) -> Self:
        unique(self.topics, "topics")
        unique(self.entity_ids, "entity_ids")
        return self


class Ambiguity(ContractModel):
    id: Text = Field(description="ID неоднозначности", examples=["a1"])
    description: Text = Field(description="Причина неоднозначности", examples=["Неизвестен автор"])
    candidate_labels: list[str] = Field(
        description="Возможные трактовки", examples=[["Автор А", "Автор Б"]]
    )
    blocks_answer: StrictBool = Field(
        description="Мешает ли неоднозначность ответу", examples=[True]
    )


class Clarification(ContractModel):
    id: Text = Field(description="ID уточнения", examples=["clarification-1"])
    question: Text = Field(
        description="Единственный уточняющий вопрос", examples=["Какого автора вы имеете в виду?"]
    )
    ambiguity_ids: list[Text] = Field(
        description="Блокирующие неоднозначности", min_length=1, examples=[["a1"]]
    )
    options: list[str] = Field(description="Подсказки; свободный ответ допустим", examples=[[]])


class ContextUpdate(ContractModel):
    base_revision: Revision = Field(
        description="Версия контекста, прочитанная анализатором", examples=[0]
    )
    subject_action: Literal["keep", "replace"] = Field(
        description="Сохранить или сменить предмет", examples=["keep"]
    )
    active_entity_ids: list[Text] = Field(
        description="Сущности предлагаемого контекста", examples=[[]]
    )
    time_scope: TimeScope | None = Field(description="Временной контекст", examples=[None])
    geography: list[str] = Field(description="Явная география вопроса", examples=[[]])
    pending_action: str | None = Field(description="Ожидаемое действие", examples=[None])


class QueryAnalysis(Envelope):
    locale: Locale = Field(description="Локаль из настроек выполнения", examples=["ru"])
    intent: Intent | None = Field(
        description="Основная содержательная задача", examples=["reference", None]
    )
    dialogue_act: Literal[
        "ask", "confirm", "clarification_reply", "rephrase", "change_subject", "cancel"
    ] = Field(description="Тип реплики", examples=["ask"])
    response_mode: Literal["focused", "thematic_overview"] = Field(
        description="Форма организации ответа", examples=["focused"]
    )
    topics: list[Topic] = Field(description="Уникальные тематики вопроса", examples=[["works"]])
    entities: list[Entity] = Field(description="Выделенные сущности", examples=[[]])
    time_scope: TimeScope | None = Field(description="Ограничение периода", examples=[None])
    geography: list[str] = Field(description="География из запроса или контекста", examples=[[]])
    subquestions: list[Subquestion] = Field(description="Допустимые подвопросы", examples=[[]])
    ambiguities: list[Ambiguity] = Field(description="Обнаруженные неоднозначности", examples=[[]])
    needs_clarification: StrictBool = Field(description="Требуется ли уточнение", examples=[False])
    clarification: Clarification | None = Field(description="Уточнение до поиска", examples=[None])
    in_scope: StrictBool = Field(
        description="Есть допустимая содержательная часть", examples=[True]
    )
    scope_status: Literal["in_scope", "mixed", "out_of_scope", "undetermined"] = Field(
        description="Граница MVP", examples=["in_scope"]
    )
    excluded_parts: list[Text] = Field(description="Исключённые части вопроса", examples=[[]])
    context_update: ContextUpdate = Field(
        description="Предложение обновить контекст",
        examples=[
            {
                "base_revision": 0,
                "subject_action": "keep",
                "active_entity_ids": [],
                "time_scope": None,
                "geography": [],
                "pending_action": None,
            }
        ],
    )

    @model_validator(mode="after")
    def consistent_analysis(self) -> Self:
        unique(self.topics, "topics")
        unique([item.entity_id for item in self.entities], "entities")
        unique([item.id for item in self.subquestions], "subquestions")
        unique([item.id for item in self.ambiguities], "ambiguities")
        unique(self.context_update.active_entity_ids, "active_entity_ids")
        if self.in_scope != (self.scope_status in {"in_scope", "mixed"}):
            raise ValueError("in_scope не соответствует scope_status")
        if self.scope_status in {"mixed", "out_of_scope"} and not self.excluded_parts:
            raise ValueError("Не объяснены исключённые части")
        if self.in_scope and not self.topics:
            raise ValueError("Допустимому вопросу нужна тематика")
        if self.needs_clarification != (self.clarification is not None):
            raise ValueError("Признак уточнения не соответствует вопросу")
        if self.clarification:
            blocking = {item.id for item in self.ambiguities if item.blocks_answer}
            references(self.clarification.ambiguity_ids, blocking, "ambiguity_ids")
        return self

    def validate_context(self, *, revision: int, entity_ids: set[str]) -> None:
        """Проверяет внешние ссылки относительно авторизованного контекста."""
        if self.context_update.base_revision != revision:
            raise ValueError("Устаревшая версия контекста")
        known = entity_ids | {item.entity_id for item in self.entities}
        references(self.context_update.active_entity_ids, known, "active_entity_ids")
        for question in self.subquestions:
            references(question.entity_ids, known, "entity_ids")
