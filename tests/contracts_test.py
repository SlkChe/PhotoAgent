"""Предметные контракты: примеры, отрицательные входы и межпакетные связи."""

import json
import unittest
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from pydantic import ValidationError

from shared.mvp_contracts import (
    Answer,
    ApiError,
    Evidence,
    ExecutionAccepted,
    ExecutionResult,
    QueryAnalysis,
    SearchPlan,
)
from shared.mvp_contracts.common import ContractModel, Operation
from shared.mvp_contracts.validation import (
    SearchLimits,
    validate_answer,
    validate_evidence,
    validate_plan,
)

EXAMPLES = json.loads(
    (Path(__file__).resolve().parents[1] / "docs/mvp-1/contract-examples.json").read_text()
)
MODELS: dict[str, type[ContractModel]] = {
    "query_analysis": QueryAnalysis,
    "search_plan": SearchPlan,
    "evidence": Evidence,
    "answer": Answer,
    "busy_error": ApiError,
    "execution_accepted": ExecutionAccepted,
    "execution_completed": ExecutionResult,
    "invitation_answer": Answer,
}


def changed(key: str, path: tuple[str | int, ...], value: object) -> dict[str, object]:
    data = deepcopy(EXAMPLES[key])
    node = data
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = value
    return cast(dict[str, object], data)


class ContractsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis = QueryAnalysis.model_validate(EXAMPLES["query_analysis"])
        self.plan = SearchPlan.model_validate(EXAMPLES["search_plan"])
        self.evidence = Evidence.model_validate(EXAMPLES["evidence"])
        self.answer = Answer.model_validate(EXAMPLES["answer"])
        self.limits = SearchLimits(
            deadline_at=self.plan.deadline_at,
            max_external_calls=self.plan.max_external_calls,
            max_total_text_chars=self.plan.max_total_text_chars,
            max_evidence_fragments=self.plan.max_evidence_fragments,
        )

    def test_all_documented_examples_roundtrip(self) -> None:
        for key, model in MODELS.items():
            with self.subTest(key=key):
                value = model.model_validate(EXAMPLES[key])
                self.assertEqual(model.model_validate_json(value.model_dump_json()), value)
        for example in EXAMPLES["other_answer_kinds"]:
            Answer.model_validate(example)

    def test_required_fields_extra_fields_and_version(self) -> None:
        for key, model in MODELS.items():
            for field in model.model_fields:
                with self.subTest(key=key, field=field):
                    data = deepcopy(EXAMPLES[key])
                    del data[field]
                    with self.assertRaises(ValidationError):
                        model.model_validate(data)
            with self.assertRaises(ValidationError):
                model.model_validate({**EXAMPLES[key], "unexpected": "value"})
            if "schema_version" in model.model_fields:
                with self.assertRaises(ValidationError):
                    model.model_validate({**EXAMPLES[key], "schema_version": "1.0"})

    def test_invalid_query(self) -> None:
        cases = [
            (("locale",), "en"),
            (("topics",), ["works", "works"]),
            (("topics",), ["theory"]),
            (("in_scope",), False),
            (("needs_clarification",), True),
            (("in_scope",), "true"),
            (("scope_status",), "mixed"),
            (("context_update", "base_revision"), -1),
            (("time_scope",), {"label": "период", "start_year": 2001, "end_year": 2000}),
        ]
        for path, value in cases:
            with self.subTest(path=path, value=value), self.assertRaises(ValidationError):
                QueryAnalysis.model_validate(changed("query_analysis", path, value))

    def test_clarification_references_blocking_ambiguity(self) -> None:
        data = deepcopy(EXAMPLES["query_analysis"])
        data.update(
            needs_clarification=True,
            ambiguities=[
                {
                    "id": "a1",
                    "description": "Неизвестный автор",
                    "candidate_labels": [],
                    "blocks_answer": True,
                }
            ],
            clarification={
                "id": "cl1",
                "question": "Какой автор?",
                "ambiguity_ids": ["a1"],
                "options": [],
            },
        )
        QueryAnalysis.model_validate(data)
        data["ambiguities"][0]["blocks_answer"] = False
        with self.assertRaises(ValidationError):
            QueryAnalysis.model_validate(data)

    def test_context_references_may_resolve_in_session(self) -> None:
        data = changed("query_analysis", ("context_update", "active_entity_ids"), ["previous"])
        analysis = QueryAnalysis.model_validate(data)
        with self.assertRaises(ValueError):
            analysis.validate_context(revision=0, entity_ids=set())
        analysis.validate_context(revision=0, entity_ids={"previous"})
        with self.assertRaises(ValueError):
            analysis.validate_context(revision=1, entity_ids={"previous"})

    def test_plan_graph_and_strict_limits(self) -> None:
        step = EXAMPLES["search_plan"]["steps"][0]
        cases = [
            (("steps",), []),
            (("max_external_calls",), 0),
            (("max_external_calls",), True),
            (("max_external_calls",), "12"),
            (("steps", 0, "depends_on"), ["missing"]),
            (("steps", 0, "depends_on"), [step["step_id"]]),
            (("steps",), [step, step]),
            (("steps", 0, "timeout_ms"), -1),
            (("deadline_at",), "2026-09-23T12:00:00"),
            (("deadline_at",), "2026-09-23T12:00:00+03:00"),
        ]
        for path, value in cases:
            with self.subTest(path=path, value=value), self.assertRaises(ValidationError):
                SearchPlan.model_validate(changed("search_plan", path, value))

    def test_plan_cycle_and_fetch(self) -> None:
        data = deepcopy(EXAMPLES["search_plan"])
        first = data["steps"][0]
        second = deepcopy(first)
        first.update(step_id="a", depends_on=["b"])
        second.update(step_id="b", depends_on=["a"])
        data["steps"] = [first, second]
        with self.assertRaises(ValidationError):
            SearchPlan.model_validate(data)
        second["depends_on"] = []
        first.update(operation="fetch", input_source_ids=[], queries=[])
        SearchPlan.model_validate(data)
        first["depends_on"] = []
        with self.assertRaises(ValidationError):
            SearchPlan.model_validate(data)

    def validate_plan(
        self, plan: SearchPlan, registry: dict[str, set[Operation]] | None = None
    ) -> None:
        # Реестр создаётся доверенным кодом теста, не содержимым модели.
        validate_plan(
            self.analysis,
            plan,
            registry=registry or {"fixture_wiki": {"search", "fetch", "entity_lookup"}},
            limits=self.limits,
            available_source_ids=set(),
        )

    def test_plan_policy_and_coverage(self) -> None:
        self.validate_plan(self.plan)
        cases = [
            (("steps", 0, "tool_id"), "unknown"),
            (("steps", 0, "subquestion_ids"), []),
            (("steps", 0, "subquestion_ids"), ["unknown"]),
            (("steps", 0, "input_source_ids"), ["invented"]),
            (("max_external_calls",), self.limits.max_external_calls + 1),
            (("max_total_text_chars",), self.limits.max_total_text_chars + 1),
            (("max_evidence_fragments",), self.limits.max_evidence_fragments + 1),
            (("deadline_at",), self.plan.deadline_at + timedelta(seconds=1)),
            (("session_id",), uuid4()),
        ]
        for path, value in cases:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.validate_plan(SearchPlan.model_validate(changed("search_plan", path, value)))
        with self.assertRaises(ValueError):
            self.validate_plan(self.plan, {"fixture_wiki": {"fetch"}})

    def test_invalid_evidence_links(self) -> None:
        cases = [
            (("fragments", 0, "source_id"), "missing"),
            (("coverage", 0, "fragment_ids"), ["missing"]),
            (("fragments", 0, "subquestion_ids"), ["missing"]),
            (("sources",), EXAMPLES["evidence"]["sources"] * 2),
            (
                ("gaps",),
                [
                    {
                        "subquestion_id": "missing",
                        "reason": "no_results",
                        "description": "Нет данных",
                    }
                ],
            ),
        ]
        for path, value in cases:
            with self.subTest(path=path), self.assertRaises(ValidationError):
                Evidence.model_validate(changed("evidence", path, value))

    def test_evidence_requires_question_coverage_and_plan_identity(self) -> None:
        validate_evidence(self.analysis, self.evidence, plan=self.plan)
        for path, value in [(("plan_id",), uuid4()), (("session_id",), uuid4())]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_evidence(
                    self.analysis,
                    Evidence.model_validate(changed("evidence", path, value)),
                    plan=self.plan,
                )
        empty = self.evidence.model_dump()
        empty.update(coverage=[], fragments=[], sources=[])
        with self.assertRaises(ValueError):
            validate_evidence(self.analysis, Evidence.model_validate(empty), plan=self.plan)
        reuse = Evidence.model_validate(changed("evidence", ("plan_id",), None))
        validate_evidence(self.analysis, reuse, plan=None)
        with self.assertRaises(ValueError):
            validate_evidence(self.analysis, self.evidence, plan=None)

    def test_citations_resolve_and_unused_material_is_rejected(self) -> None:
        cases = [
            (("claims", 0, "fragment_ids"), ["missing"]),
            (("claims", 0, "fragment_ids"), []),
            (("fragments", 0, "source_id"), "missing"),
            (("claims",), EXAMPLES["answer"]["claims"] * 2),
            (("claims",), []),
            (("locale",), "en"),
            (("direct_answer",), "  "),
            (
                ("sections",),
                [
                    {
                        "section_id": "s",
                        "heading": None,
                        "text": "Контекст",
                        "claim_ids": ["missing"],
                    }
                ],
            ),
        ]
        for path, value in cases:
            with self.subTest(path=path), self.assertRaises(ValidationError):
                Answer.model_validate(changed("answer", path, value))

    def test_invitation_and_limited_answer(self) -> None:
        for path, value in [
            (("follow_ups",), ["Продолжим"]),
            (("completeness",), "complete"),
            (("limitations",), ["Недостаточно данных"]),
        ]:
            with self.subTest(path=path), self.assertRaises(ValidationError):
                Answer.model_validate(changed("invitation_answer", path, value))
        with self.assertRaises(ValidationError):
            Answer.model_validate(changed("answer", ("completeness",), "limited"))
        data = deepcopy(EXAMPLES["answer"])
        data.update(claims=[], fragments=[], sources=[])
        with self.assertRaises(ValidationError):
            Answer.model_validate(data)

    def test_url_validation_preserves_exact_spelling(self) -> None:
        for url in [
            "file:///etc/passwd",
            "javascript:alert(1)",
            "https://u:p@example.org",
            " https://example.org",
            "https://example.org/a\nb",
        ]:
            with self.subTest(url=url), self.assertRaises(ValidationError):
                Answer.model_validate(changed("answer", ("sources", 0, "url"), url))
        for url in [
            "https://example.org",
            "https://example.org/?a=1&b=2",
            "https://example.org/?b=2&a=1",
        ]:
            answer = Answer.model_validate(changed("answer", ("sources", 0, "url"), url))
            self.assertEqual(answer.sources[0].url, url)

    def test_evidence_provenance_is_not_replaced_by_generator(self) -> None:
        validate_answer(self.answer, self.evidence, analysis=self.analysis)
        cases = [
            (("sources", 0, "url"), "https://example.net/invented"),
            (("sources", 0, "access_mode"), "snippet"),
            (("sources", 0, "retrieved_at"), "2026-09-24T12:00:00Z"),
            (("sources", 0, "usage_constraints"), []),
            (("fragments", 0, "text"), "Придуманный текст"),
            (("claims", 0, "statement"), "Не встречается в ответе"),
            (("claims", 0, "status"), "disputed"),
            (("execution_id",), uuid4()),
        ]
        for path, value in cases:
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_answer(
                    Answer.model_validate(changed("answer", path, value)),
                    self.evidence,
                    analysis=self.analysis,
                )

    def test_partial_retrieval_requires_limitations(self) -> None:
        evidence = Evidence.model_validate(changed("evidence", ("retrieval_status",), "partial"))
        with self.assertRaises(ValueError):
            validate_answer(self.answer, evidence, analysis=self.analysis)
        data = deepcopy(EXAMPLES["answer"])
        data.update(completeness="limited", limitations=["Поиск выполнен частично"])
        validate_answer(Answer.model_validate(data), evidence, analysis=self.analysis)

    def test_execution_payloads_and_foreign_answer(self) -> None:
        cases = [
            (("answer",), None),
            (("status",), "queued"),
            (("status",), "failed"),
            (("answer", "session_id"), uuid4()),
        ]
        for path, value in cases:
            with self.subTest(path=path), self.assertRaises(ValidationError):
                ExecutionResult.model_validate(changed("execution_completed", path, value))
        data = deepcopy(EXAMPLES["execution_completed"])
        data.update(
            status="failed",
            answer=None,
            error={"code": "provider_error", "message": "Ошибка сервиса", "retryable": True},
        )
        ExecutionResult.model_validate(data)
        with self.assertRaises(ValidationError):
            ApiError.model_validate(changed("busy_error", ("active_execution_id",), None))

    def test_openapi_models_have_documented_required_fields(self) -> None:
        app = FastAPI()

        @app.post("/contract-check", response_model=Answer)
        async def contract_check(analysis: QueryAnalysis) -> Answer:
            return self.answer

        schemas = app.openapi()["components"]["schemas"]
        for model in MODELS.values():
            schema = model.model_json_schema()
            for definition in [schema, *schema.get("$defs", {}).values()]:
                if "properties" not in definition:
                    continue
                self.assertEqual(definition.get("additionalProperties"), False)
                self.assertEqual(set(definition["properties"]), set(definition["required"]))
                for field in definition["properties"].values():
                    self.assertTrue(field.get("description"))
        self.assertIn("invitation", schemas["Answer"]["properties"]["kind"]["enum"])
        self.assertEqual(schemas["Locale"]["const"], "ru")
