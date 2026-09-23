"""Полученные источники, фрагменты, покрытие и противоречия."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from .common import ContractModel, Envelope, Text, UtcDatetime, WebUrl, references, unique


class AnswerSource(ContractModel):
    source_id: Text = Field(description="ID источника внутри пакета", examples=["s1"])
    url: WebUrl = Field(
        description="Точный URL HTTP/HTTPS без нормализации", examples=["https://example.org/photo"]
    )
    title: Text = Field(description="Название материала", examples=["Каталог фотографий"])
    author_or_organization: str | None = Field(description="Автор или организация", examples=[None])
    published_date: str | None = Field(
        description="Дата публикации с доступной точностью", examples=["2000", None]
    )
    retrieved_at: UtcDatetime = Field(
        description="Исходное время получения UTC", examples=["2026-09-23T12:00:00Z"]
    )
    source_type: Literal["primary", "secondary", "encyclopedia", "other"] = Field(
        description="Тип источника", examples=["primary"]
    )
    access_mode: Literal["full_text", "excerpt", "snippet"] = Field(
        description="Реально доступный объём текста", examples=["excerpt"]
    )
    usage_constraints: list[str] = Field(
        description="Ограничения использования материала", examples=[[]]
    )


class Source(AnswerSource):
    provider_id: Text = Field(description="Технический ID адаптера", examples=["fixture_wiki"])
    origin_group: str | None = Field(
        description="Общее происхождение; null не означает независимость", examples=[None]
    )


class AnswerFragment(ContractModel):
    fragment_id: Text = Field(description="ID полученного фрагмента", examples=["f1"])
    source_id: Text = Field(description="Источник фрагмента", examples=["s1"])
    text: Text = Field(
        description="Оригинальный полученный текст", examples=["Серия создана в 2000 году."]
    )
    locator: str | None = Field(description="Страница или раздел", examples=[None])


class Fragment(AnswerFragment):
    subquestion_ids: list[Text] = Field(description="Связанные подвопросы", examples=[["q1"]])


class Coverage(ContractModel):
    subquestion_id: Text = Field(description="Покрываемый подвопрос", examples=["q1"])
    status: Literal["sufficient", "limited", "missing"] = Field(
        description="Оценка покрытия, не истинности", examples=["sufficient"]
    )
    fragment_ids: list[Text] = Field(description="Полученные опорные фрагменты", examples=[["f1"]])


class ConflictVersion(ContractModel):
    statement: Text = Field(
        description="Одна версия спорного утверждения", examples=["Серия создана в 2000 году"]
    )
    fragment_ids: list[Text] = Field(
        description="Опора этой версии", min_length=1, examples=[["f1"]]
    )


class Conflict(ContractModel):
    conflict_id: Text = Field(description="ID противоречия", examples=["conflict-1"])
    subquestion_id: Text = Field(description="Связанный подвопрос", examples=["q1"])
    description: Text = Field(description="Описание расхождения", examples=["Разные даты создания"])
    versions: list[ConflictVersion] = Field(
        description="Не менее двух версий",
        min_length=2,
        examples=[
            [
                {"statement": "2000 год", "fragment_ids": ["f1"]},
                {"statement": "2001 год", "fragment_ids": ["f2"]},
            ]
        ],
    )


class Gap(ContractModel):
    subquestion_id: str | None = Field(
        description="Подвопрос или общая проблема", examples=["q1", None]
    )
    reason: Literal[
        "no_results",
        "timeout",
        "provider_error",
        "snippet_only",
        "budget_exhausted",
        "unresolved_identity",
        "restricted_access",
    ] = Field(description="Безопасная причина пробела", examples=["no_results"])
    description: Text = Field(description="Объяснение ограничения", examples=["Источник не найден"])


class Evidence(Envelope):
    evidence_id: UUID = Field(
        description="ID пакета доказательств", examples=["55555555-5555-4555-8555-555555555555"]
    )
    plan_id: UUID | None = Field(description="План или null при reuse", examples=[None])
    sources: list[Source] = Field(description="Источники пакета", examples=[[]])
    fragments: list[Fragment] = Field(description="Оригинальные фрагменты", examples=[[]])
    coverage: list[Coverage] = Field(description="Покрытие каждого подвопроса", examples=[[]])
    conflicts: list[Conflict] = Field(description="Обнаруженные противоречия", examples=[[]])
    gaps: list[Gap] = Field(description="Нехватка сведений и ошибки поиска", examples=[[]])
    retrieval_status: Literal["complete", "partial", "empty", "failed"] = Field(
        description="Исполнение поиска, не полнота знаний", examples=["complete"]
    )

    @model_validator(mode="after")
    def resolved_references(self) -> Self:
        sources = unique([item.source_id for item in self.sources], "sources")
        fragments = unique([item.fragment_id for item in self.fragments], "fragments")
        questions = unique([item.subquestion_id for item in self.coverage], "coverage")
        unique([item.conflict_id for item in self.conflicts], "conflicts")
        for item in self.fragments:
            references([item.source_id], sources, "fragment.source_id")
            references(item.subquestion_ids, questions, "fragment.subquestion_ids")
        for item in self.coverage:
            references(item.fragment_ids, fragments, "coverage.fragment_ids")
        for item in self.conflicts:
            references([item.subquestion_id], questions, "conflict.subquestion_id")
            for version in item.versions:
                references(version.fragment_ids, fragments, "conflict.fragment_ids")
        for item in self.gaps:
            if item.subquestion_id is not None:
                references([item.subquestion_id], questions, "gap.subquestion_id")
        return self
