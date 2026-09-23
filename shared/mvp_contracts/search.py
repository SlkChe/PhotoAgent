"""Конечный план разрешённых поисковых операций."""

from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from .common import (
    ContractModel,
    Envelope,
    Operation,
    PositiveInt,
    Text,
    UtcDatetime,
    references,
    unique,
)


class SearchStep(ContractModel):
    step_id: Text = Field(description="ID шага", examples=["step-1"])
    subquestion_ids: list[Text] = Field(description="Покрываемые подвопросы", examples=[["q1"]])
    tool_id: Text = Field(
        description="ID зарегистрированного инструмента", examples=["fixture_wiki"]
    )
    operation: Operation = Field(description="Разрешённая операция", examples=["search"])
    queries: list[str] = Field(
        description="Поисковые формулировки", examples=[["история фотографии"]]
    )
    languages: list[str] = Field(
        description="Языки поиска, не локаль ответа", examples=[["ru", "en"]]
    )
    preferred_source_types: list[str] = Field(
        description="Предпочитаемые типы материалов", examples=[["primary"]]
    )
    depends_on: list[Text] = Field(description="Предшествующие шаги", examples=[[]])
    input_source_ids: list[Text] = Field(
        description="Источники предыдущих результатов", examples=[[]]
    )
    max_results: PositiveInt = Field(description="Предел результатов шага", examples=[3])
    timeout_ms: PositiveInt = Field(description="Таймаут шага, мс", examples=[5000])


class SearchPlan(Envelope):
    plan_id: UUID = Field(description="ID плана", examples=["44444444-4444-4444-8444-444444444444"])
    steps: list[SearchStep] = Field(
        description="Шаги конечного графа",
        min_length=1,
        examples=[
            [
                {
                    "step_id": "step-1",
                    "subquestion_ids": ["q1"],
                    "tool_id": "fixture_wiki",
                    "operation": "search",
                    "queries": ["пикториализм"],
                    "languages": ["ru"],
                    "preferred_source_types": ["primary"],
                    "depends_on": [],
                    "input_source_ids": [],
                    "max_results": 3,
                    "timeout_ms": 5000,
                }
            ]
        ],
    )
    deadline_at: UtcDatetime = Field(
        description="Предельное время поиска UTC", examples=["2026-09-23T12:00:00Z"]
    )
    max_external_calls: PositiveInt = Field(
        description="Все вызовы с чтением и повторами", examples=[12]
    )
    max_total_text_chars: PositiveInt = Field(
        description="Суммарный предел входных текстов", examples=[20000]
    )
    max_evidence_fragments: PositiveInt = Field(description="Предел фрагментов", examples=[12])

    @model_validator(mode="after")
    def acyclic_graph(self) -> Self:
        ids = unique([item.step_id for item in self.steps], "steps")
        remaining = {}
        for step in self.steps:
            references(step.depends_on, ids, "depends_on")
            unique(step.subquestion_ids, "subquestion_ids")
            unique(step.input_source_ids, "input_source_ids")
            remaining[step.step_id] = set(step.depends_on)
            if step.operation == "fetch" and not (step.input_source_ids or step.depends_on):
                raise ValueError("Fetch требует полученный источник или зависимый шаг")
        while remaining:
            ready = {key for key, parents in remaining.items() if not parents}
            if not ready:
                raise ValueError("Цикл в поисковом плане")
            remaining = {
                key: parents - ready for key, parents in remaining.items() if key not in ready
            }
        return self
