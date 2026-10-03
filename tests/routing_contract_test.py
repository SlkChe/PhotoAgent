"""Раздельные ведущий профиль, назначения и авторство по принятой A-13."""

import json
import unittest
from copy import deepcopy
from pathlib import Path

from pydantic import ValidationError

from shared.http_draft.operations import RoleRef
from shared.http_draft.routing import RoutingDecision
from shared.http_draft.session import ExecutionView, SessionSnapshot
from shared.mvp_contracts import QueryAnalysis


class RoutingContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.examples = {
            c["id"]: c["payload"]
            for c in json.loads(Path("docs/mvp-1/http-contract-examples.json").read_text())[
                "examples"
            ]
        }
        self.analysis = json.loads(Path("docs/mvp-1/contract-examples.json").read_text())[
            "query_analysis"
        ]

    def test_first_addressed_can_sign_other_leading_profile(self) -> None:
        decision = RoutingDecision.model_validate(self.examples["routing-first-addressed"])
        view = ExecutionView.model_validate(self.examples["execution-different-author"])
        snapshot = SessionSnapshot.model_validate(self.examples["snapshot-different-author"])
        self.assertNotEqual(view.execution.selected_role, view.author)
        self.assertEqual(view.execution.selected_role, decision.selected_role)
        self.assertEqual(snapshot.messages[1].author, view.author)
        decision.validate_execution(view)
        with self.assertRaises(ValueError):
            decision.validate_publication(view.answer, author=view.execution.selected_role)

    def test_author_rules_cannot_be_bypassed(self) -> None:
        source = self.examples["routing-first-addressed"]
        for changes in (
            {"author_basis": "selected"},
            {"addressed_roles": []},
            {"main_subquestion_id": None},
            {"route_basis": "topic"},
            {"addressed_roles": [source["addressed_roles"][0]] * 2},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                RoutingDecision.model_validate({**source, **changes})

    def test_consolidation_covers_allowed_questions_once(self) -> None:
        decision = RoutingDecision.model_validate(self.examples["routing-consolidated"])
        second = deepcopy(self.analysis["subquestions"][0])
        second["id"] = "q2"
        self.analysis["subquestions"].append(second)
        analysis = QueryAnalysis.model_validate(self.analysis)
        decision.validate_analysis(analysis, revision=0)
        for changes in (
            {"author_basis": "first_addressed"},
            {"main_subquestion_id": "q1"},
            {"selected_role": self.examples["routing-single"]["selected_role"]},
            {"subquestion_roles": decision.model_dump()["subquestion_roles"][:1]},
            {"subquestion_roles": decision.model_dump()["subquestion_roles"] * 2},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                RoutingDecision.model_validate({**decision.model_dump(), **changes})

    def test_routing_rejects_foreign_analysis_and_stale_revision(self) -> None:
        decision = RoutingDecision.model_validate(self.examples["routing-single"])
        analysis = QueryAnalysis.model_validate(self.analysis)
        decision.validate_analysis(analysis, revision=0)
        with self.assertRaises(ValueError):
            decision.validate_analysis(analysis, revision=1)
        for field in ("session_id", "request_id", "execution_id"):
            foreign = {**self.analysis, field: "00000000-0000-4000-8000-000000000099"}
            with self.subTest(field=field), self.assertRaises(ValueError):
                decision.validate_analysis(QueryAnalysis.model_validate(foreign), revision=0)
        analysis = analysis.model_copy(update={"subquestions": []})
        with self.assertRaises(ValueError):
            decision.validate_analysis(analysis, revision=0)

    def test_unknown_invitation_and_failure_have_distinct_authorship(self) -> None:
        decision = RoutingDecision.model_validate(self.examples["routing-unknown-invitation"])
        view = ExecutionView.model_validate(self.examples["execution-unknown-invitation"])
        decision.validate_publication(view.answer, author=view.author)
        failed = ExecutionView.model_validate(self.examples["execution-failed-after-selection"])
        self.assertIsNotNone(failed.execution.selected_role)
        self.assertIsNone(failed.author)
        bad = deepcopy(self.examples["execution-failed-after-selection"])
        bad["author"] = bad["execution"]["selected_role"]
        with self.assertRaises(ValidationError):
            ExecutionView.model_validate(bad)

    def test_missing_selection_and_old_version_are_rejected(self) -> None:
        source = self.examples["execution-completed"]
        bad = deepcopy(source)
        bad["execution"]["selected_role"] = None
        with self.assertRaises(ValidationError):
            ExecutionView.model_validate(bad)
        with self.assertRaises(ValidationError):
            ExecutionView.model_validate({**source, "contract_version": "mvp1-http-draft.1"})
        with self.assertRaises(ValidationError):
            RoleRef(role_id="invented", display_name="Новый")
