"""Проверяемость кандидата B-01 без изменения работающего API."""

import copy
import json
import re
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from scripts.build_http_contract import DESTINATION, MODELS, build_contract
from scripts.preview_http_contract import app
from shared.http_draft.operations import FeedbackUpdate
from shared.http_draft.session import ExecutionView, SessionSnapshot


class HttpContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.examples = json.loads(Path("docs/mvp-1/http-contract-examples.json").read_text())[
            "examples"
        ]
        cls.models = {model.__name__: model for model in MODELS}
        cls.by_id = {case["id"]: case["payload"] for case in cls.examples}

    def test_all_examples_roundtrip_and_unknown_fields(self) -> None:
        self.assertEqual(len(self.examples), len(self.by_id))
        for case in self.examples:
            with self.subTest(case=case["id"]):
                model = self.models[case["model"]]
                parsed = model.model_validate(case["payload"])
                self.assertEqual(model.model_validate_json(parsed.model_dump_json()), parsed)
                with self.assertRaises(ValidationError):
                    model.model_validate({**case["payload"], "unexpected": "test"})

    def test_snapshot_rejects_foreign_answers_and_wrong_status(self) -> None:
        source = self.by_id["snapshot-completed"]
        for mutation in ("owner", "execution", "status", "ttl", "missing_user"):
            candidate = copy.deepcopy(source)
            if mutation == "owner":
                candidate["messages"][1]["answer"]["session_id"] = (
                    "00000000-0000-4000-8000-000000000099"
                )
            elif mutation == "execution":
                candidate["messages"][0]["request_id"] = "00000000-0000-4000-8000-000000000099"
            elif mutation == "status":
                candidate["session_status"] = "in_progress"
            elif mutation == "ttl":
                candidate["expires_at"] = candidate["last_activity_at"]
            else:
                candidate["messages"].pop(0)
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                SessionSnapshot.model_validate(candidate)

    def test_first_source_card_cannot_move_to_later_answer(self) -> None:
        candidate = copy.deepcopy(self.by_id["snapshot-second-role-same-url"])
        candidate["source_cards"][0]["first_answer_id"] = candidate["messages"][3]["answer"][
            "answer_id"
        ]
        with self.assertRaises(ValidationError):
            SessionSnapshot.model_validate(candidate)
        candidate = copy.deepcopy(self.by_id["snapshot-second-role-same-url"])
        candidate["source_cards"][0]["context_comment"] = "Другой контекст"
        with self.assertRaises(ValidationError):
            SessionSnapshot.model_validate(candidate)

    def test_feedback_is_not_generator_data(self) -> None:
        candidate = copy.deepcopy(self.by_id["snapshot-awaiting-clarification"])
        candidate["answer_states"][0]["eligible"] = True
        with self.assertRaises(ValidationError):
            SessionSnapshot.model_validate(candidate)
        with self.assertRaises(ValidationError):
            FeedbackUpdate.model_validate(
                {**self.by_id["feedback-positive-removes-comment"], "comment": "test"}
            )
        candidate = copy.deepcopy(self.by_id["execution-completed"])
        candidate["author"] = None
        with self.assertRaises(ValidationError):
            ExecutionView.model_validate(candidate)

    def test_openapi_is_reproducible_and_references_resolve(self) -> None:
        actual = json.loads(DESTINATION.read_text())
        self.assertEqual(actual, build_contract())
        schemas = actual["components"]["schemas"]
        for ref in re.findall(r'"\$ref": "([^"]+)"', json.dumps(actual)):
            self.assertTrue(ref.startswith("#/components/schemas/"))
            self.assertIn(ref.rsplit("/", 1)[1], schemas)
        names = []
        for path, item in actual["paths"].items():
            for route in item.values():
                names.append(route["operationId"])
                parameters = {p["name"] for p in route["parameters"] if p["in"] == "path"}
                self.assertEqual(parameters, set(re.findall(r"{([^}]+)}", path)))
                for status, response in route["responses"].items():
                    if status == "204":
                        self.assertNotIn("content", response)
                    elif int(status) >= 400:
                        self.assertEqual(
                            response["content"]["application/json"]["schema"]["$ref"],
                            "#/components/schemas/ApiError",
                        )
        self.assertEqual(len(names), 14)
        self.assertEqual(len(names), len(set(names)))

    def test_preview_does_not_implement_api(self) -> None:
        with TestClient(app) as client:
            self.assertEqual(client.get("/openapi.json").json(), build_contract())
            self.assertIn('"supportedSubmitMethods": []', client.get("/docs").text)
            self.assertEqual(client.get("/mvp1/internal/session").status_code, 404)

    def test_domain_answer_schema_remains_unchanged(self) -> None:
        from shared.mvp_contracts.answer import Answer

        self.assertNotIn("author", Answer.model_fields)
        schema = build_contract()["components"]["schemas"]["Answer"]
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.1")
        self.assertNotIn("contract_version", schema["properties"])
