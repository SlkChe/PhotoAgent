"""Проверки связей пакетов и политики; не авторизация или семантическая экспертиза."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from .answer import Answer
from .common import Envelope, Operation, references
from .evidence import Evidence
from .query import QueryAnalysis
from .search import SearchPlan


@dataclass(frozen=True)
class SearchLimits:
    """Утверждённый остаток бюджета, предоставляемый оркестратором."""

    deadline_at: datetime
    max_external_calls: int
    max_total_text_chars: int
    max_evidence_fragments: int


def same_execution(left: Envelope, right: Envelope) -> None:
    for key in ("session_id", "request_id", "execution_id"):
        if getattr(left, key) != getattr(right, key):
            raise ValueError("Пакеты принадлежат разным выполнениям")


def validate_plan(
    analysis: QueryAnalysis,
    plan: SearchPlan,
    *,
    registry: Mapping[str, set[Operation]],
    limits: SearchLimits,
    available_source_ids: set[str],
) -> None:
    """Проверяет допустимость поиска, покрытие и ограничения доверенной политики."""
    same_execution(analysis, plan)
    if analysis.needs_clarification or not analysis.in_scope:
        raise ValueError("Поиск до уточнения или вне MVP запрещён")
    questions = {item.id for item in analysis.subquestions}
    if not questions:
        raise ValueError("План не имеет подвопросов")
    covered: set[str] = set()
    for step in plan.steps:
        if step.operation not in registry.get(step.tool_id, set()):
            raise ValueError("Инструмент или операция не разрешены реестром")
        references(step.subquestion_ids, questions, "step.subquestion_ids")
        references(step.input_source_ids, available_source_ids, "input_source_ids")
        covered.update(step.subquestion_ids)
    if covered != questions:
        raise ValueError("Не все подвопросы покрыты планом")
    if plan.deadline_at > limits.deadline_at:
        raise ValueError("План превышает общий deadline")
    for key in ("max_external_calls", "max_total_text_chars", "max_evidence_fragments"):
        if getattr(plan, key) > getattr(limits, key):
            raise ValueError("План превышает общий бюджет")


def validate_evidence(
    analysis: QueryAnalysis, evidence: Evidence, *, plan: SearchPlan | None
) -> None:
    """Связывает покрытие с вопросом и пакетом результата поиска или reuse."""
    same_execution(analysis, evidence)
    questions = {item.id for item in analysis.subquestions}
    if {item.subquestion_id for item in evidence.coverage} != questions:
        raise ValueError("Evidence не покрывает набор подвопросов анализа")
    if plan is None:
        if evidence.plan_id is not None:
            raise ValueError("Reuse не должен приписывать себе новый поиск")
    else:
        same_execution(plan, evidence)
        if evidence.plan_id != plan.plan_id:
            raise ValueError("Evidence относится к другому плану")
        if len(evidence.fragments) > plan.max_evidence_fragments:
            raise ValueError("Превышен предел фрагментов")


def validate_answer(answer: Answer, evidence: Evidence, *, analysis: QueryAnalysis) -> None:
    """Не позволяет подменить полученные тексты/URL, происхождение и ограничения."""
    same_execution(analysis, answer)
    same_execution(evidence, answer)
    if answer.locale != analysis.locale:
        raise ValueError("Локаль ответа отличается от локали выполнения")
    sources = {item.source_id: item for item in evidence.sources}
    fragments = {item.fragment_id: item for item in evidence.fragments}
    for source in answer.sources:
        original = sources.get(source.source_id)
        if original is None or source.model_dump() != original.model_dump(
            exclude={"provider_id", "origin_group"}
        ):
            raise ValueError("Источник ответа не соответствует Evidence")
    for fragment in answer.fragments:
        original = fragments.get(fragment.fragment_id)
        if original is None or fragment.model_dump() != original.model_dump(
            exclude={"subquestion_ids"}
        ):
            raise ValueError("Фрагмент ответа не соответствует Evidence")
    if answer.kind in {"answer", "insufficient_evidence"}:
        limited = (
            analysis.scope_status == "mixed"
            or evidence.retrieval_status != "complete"
            or bool(evidence.gaps)
            or any(item.status != "sufficient" for item in evidence.coverage)
        )
        if limited and (answer.completeness != "limited" or not answer.limitations):
            raise ValueError("Ограничения поиска не отражены в ответе")
    _validate_claims(answer, evidence)


def _validate_claims(answer: Answer, evidence: Evidence) -> None:
    texts = [answer.direct_answer, *(item.text for item in answer.sections)]
    normalized = [" ".join(text.split()) for text in texts]
    for claim in answer.claims:
        if not any(" ".join(claim.statement.split()) in text for text in normalized):
            raise ValueError("Утверждение отсутствует в тексте ответа")
        if claim.status == "disputed":
            used = set(claim.fragment_ids)
            supported_versions = [
                sum(bool(used.intersection(version.fragment_ids)) for version in conflict.versions)
                for conflict in evidence.conflicts
            ]
            if not any(count >= 2 for count in supported_versions):
                raise ValueError("Спорное утверждение не представляет разные версии Evidence")
