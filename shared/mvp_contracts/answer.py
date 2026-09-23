"""Самодостаточный публичный ответ и проверка цепочки цитирования."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from .common import ContractModel, Envelope, Locale, Text, references, unique
from .evidence import AnswerFragment, AnswerSource


class AnswerStyle(ContractModel):
    detail: Literal["brief", "detailed"] = Field(
        description="Подробность объяснения", examples=["brief"]
    )
    level: Literal["beginner", "advanced"] = Field(
        description="Уровень читателя", examples=["beginner"]
    )


class AnswerSection(ContractModel):
    section_id: Text = Field(description="ID раздела ответа", examples=["section-1"])
    heading: str | None = Field(description="Необязательный заголовок", examples=[None])
    text: Text = Field(description="Текст раздела", examples=["Исторический контекст"])
    claim_ids: list[Text] = Field(description="Утверждения раздела", examples=[["c1"]])


class Claim(ContractModel):
    claim_id: Text = Field(description="ID проверяемого утверждения", examples=["c1"])
    statement: Text = Field(
        description="Утверждение из текста ответа", examples=["Серия создана в 2000 году."]
    )
    status: Literal["supported", "disputed", "uncertain"] = Field(
        description="Статус подтверждения", examples=["supported"]
    )
    fragment_ids: list[Text] = Field(description="Опорные фрагменты", examples=[["f1"]])

    @model_validator(mode="after")
    def supported_has_evidence(self) -> Self:
        unique(self.fragment_ids, "claim.fragment_ids")
        if self.status in {"supported", "disputed"} and not self.fragment_ids:
            raise ValueError("Утверждение требует опорных фрагментов")
        return self


class AnswerClarification(ContractModel):
    id: Text = Field(description="ID ожидаемого уточнения", examples=["clarification-1"])
    question: Text = Field(
        description="Уточняющий вопрос", examples=["Какого автора вы имеете в виду?"]
    )
    options: list[str] = Field(description="Варианты подсказок", examples=[[]])


class Answer(Envelope):
    answer_id: UUID = Field(
        description="ID ответа, назначенный API", examples=["66666666-6666-4666-8666-666666666666"]
    )
    locale: Locale = Field(description="Локаль принятого выполнения", examples=["ru"])
    kind: Literal[
        "answer", "clarification", "out_of_scope", "insufficient_evidence", "invitation"
    ] = Field(description="Вид ответа", examples=["answer"])
    completeness: Literal["complete", "limited", "not_applicable"] = Field(
        description="Полнота ответа", examples=["complete"]
    )
    direct_answer: Text = Field(
        description="Прямой ответ или служебное сообщение", examples=["Серия создана в 2000 году."]
    )
    sections: list[AnswerSection] = Field(description="Разделы ответа", examples=[[]])
    claims: list[Claim] = Field(description="Проверяемые утверждения", examples=[[]])
    fragments: list[AnswerFragment] = Field(
        description="Только использованные публичные фрагменты", examples=[[]]
    )
    sources: list[AnswerSource] = Field(
        description="Только источники этих фрагментов", examples=[[]]
    )
    limitations: list[Text] = Field(description="Оговорки и непокрытые части", examples=[[]])
    clarification: AnswerClarification | None = Field(
        description="Вопрос при kind=clarification", examples=[None]
    )
    follow_ups: list[str] = Field(description="Предложения продолжения", examples=[[]])
    style: AnswerStyle = Field(
        description="Стиль принятого выполнения",
        examples=[{"detail": "brief", "level": "beginner"}],
    )

    @model_validator(mode="after")
    def consistent_kind(self) -> Self:
        if (self.kind == "clarification") != (self.clarification is not None):
            raise ValueError("Уточнение не соответствует kind")
        expected = {
            "clarification": "not_applicable",
            "out_of_scope": "not_applicable",
            "invitation": "not_applicable",
            "insufficient_evidence": "limited",
        }
        if self.kind in expected and self.completeness != expected[self.kind]:
            raise ValueError("Полнота не соответствует kind")
        if self.kind == "answer" and self.completeness == "not_applicable":
            raise ValueError("Для содержательного ответа нужна оценка полноты")
        if self.completeness == "limited" and not self.limitations:
            raise ValueError("Неполный ответ требует оговорок")
        if self.kind == "invitation" and any(
            (
                self.sections,
                self.claims,
                self.fragments,
                self.sources,
                self.limitations,
                self.follow_ups,
            )
        ):
            raise ValueError("Приглашение не содержит доказательств и продолжений")
        if self.kind == "answer" and not self.fragments:
            raise ValueError("Пустая доказательная база: используйте insufficient_evidence")
        return self

    @model_validator(mode="after")
    def resolved_citations(self) -> Self:
        claims = unique([item.claim_id for item in self.claims], "claims")
        fragments = unique([item.fragment_id for item in self.fragments], "fragments")
        sources = unique([item.source_id for item in self.sources], "sources")
        unique([item.section_id for item in self.sections], "sections")
        used_fragments: set[str] = set()
        for claim in self.claims:
            references(claim.fragment_ids, fragments, "claim.fragment_ids")
            used_fragments.update(claim.fragment_ids)
        for section in self.sections:
            references(section.claim_ids, claims, "section.claim_ids")
        for fragment in self.fragments:
            references([fragment.source_id], sources, "fragment.source_id")
        if used_fragments != fragments:
            raise ValueError("Ответ содержит неиспользованные фрагменты")
        if {item.source_id for item in self.fragments} != sources:
            raise ValueError("Ответ содержит неиспользованные источники")
        return self
