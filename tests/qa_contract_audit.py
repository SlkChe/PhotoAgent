"""Независимый аудит T-03; запускать отдельно, дефекты описаны в test-plan.md."""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from photo_api.session_probe.app import COOKIE, create_app
from photo_ui.mvp_client.client import DraftApiClient
from photo_ui.mvp_client.state import DeliveryState
from photo_ui.mvp_client.transport import ClientError, ClientSettings
from shared.http_draft.session import SessionSnapshot
from shared.mvp_contracts import Answer, Evidence, QueryAnalysis
from shared.mvp_contracts.evidence import AnswerSource
from shared.mvp_contracts.validation import validate_answer
from shared.session_actions import SessionActionRequest

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = json.loads((ROOT / "docs/mvp-1/contract-examples.json").read_text())
HTTP = {
    item["id"]: item["payload"]
    for item in json.loads((ROOT / "docs/mvp-1/http-contract-examples.json").read_text())[
        "examples"
    ]
}
FOREIGN = "00000000-0000-4000-8000-000000000099"


class IndependentContractAudit(unittest.TestCase):
    def test_nullable_metadata_accepts_null_and_partial_date(self) -> None:
        data = deepcopy(DOMAIN["answer"]["sources"][0])
        data.update(author_or_organization=None, published_date=None)
        AnswerSource.model_validate(data)
        data["published_date"] = "1900"
        self.assertEqual(AnswerSource.model_validate(data).published_date, "1900")

    def test_nullable_metadata_rejects_empty_unknown_values(self) -> None:
        # QA-D01: contracts.md требует null вместо пустой строки для неизвестного.
        for field in ("author_or_organization", "published_date"):
            for value in ("", "   "):
                data = deepcopy(DOMAIN["answer"]["sources"][0])
                data[field] = value
                with self.subTest(field=field, blank=len(value)):
                    with self.assertRaises(ValidationError):
                        AnswerSource.model_validate(data)

    def test_reused_source_preserves_retrieval_time(self) -> None:
        analysis = QueryAnalysis.model_validate(DOMAIN["query_analysis"])
        evidence = Evidence.model_validate(DOMAIN["evidence"])
        data = deepcopy(DOMAIN["answer"])
        validate_answer(Answer.model_validate(data), evidence, analysis=analysis)
        data["sources"][0]["retrieved_at"] = "2026-10-01T00:00:00Z"
        with self.assertRaises(ValueError):
            validate_answer(Answer.model_validate(data), evidence, analysis=analysis)

    def test_invented_fragment_text_is_rejected(self) -> None:
        data = deepcopy(DOMAIN["answer"])
        data["fragments"][0]["text"] = "Синтетический текст, отсутствующий в Evidence."
        with self.assertRaises(ValueError):
            validate_answer(
                Answer.model_validate(data),
                Evidence.model_validate(DOMAIN["evidence"]),
                analysis=QueryAnalysis.model_validate(DOMAIN["query_analysis"]),
            )

    def test_action_ids_are_required_and_not_coerced_from_null(self) -> None:
        valid = {"request_id": FOREIGN, "expected_session_id": DOMAIN["answer"]["session_id"]}
        SessionActionRequest.model_validate(valid)
        for field in valid:
            for value in (None, "", 1, True, [], {}):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        SessionActionRequest.model_validate({**valid, field: value})

    def test_source_card_keeps_first_metadata_after_role_change(self) -> None:
        data = deepcopy(HTTP["snapshot-second-role-same-url"])
        snapshot = SessionSnapshot.model_validate(data)
        self.assertNotEqual(snapshot.messages[1].author, snapshot.messages[3].author)
        data["source_cards"][0]["source"]["title"] = "Подмена первичного заголовка"
        with self.assertRaises(ValidationError):
            SessionSnapshot.model_validate(data)

    def test_old_revision_cannot_replace_new_snapshot(self) -> None:
        state = DeliveryState()
        current = SessionSnapshot.model_validate(HTTP["snapshot-empty"])
        data = deepcopy(HTTP["snapshot-empty"])
        data["revision"] = current.revision + 1
        latest = SessionSnapshot.model_validate(data)
        state.restore(latest)
        state.restore(current)
        self.assertEqual(state.snapshot, latest)

    def test_foreign_snapshot_preserves_pending_input(self) -> None:
        state = DeliveryState()
        state.restore(SessionSnapshot.model_validate(HTTP["snapshot-empty"]))
        request = state.prepare("Синтетический вопрос")
        data = deepcopy(HTTP["snapshot-empty"])
        data["session_id"] = FOREIGN
        with self.assertRaises(ClientError):
            state.restore(SessionSnapshot.model_validate(data))
        self.assertEqual(state.draft, request.text)
        self.assertIsNotNone(state.pending_json)
        self.assertFalse(state.synchronized)

    def test_execution_rejects_foreign_owner_with_matching_execution_id(self) -> None:
        # QA-D02: F-02 проверяет execution_id, но не владельца при polling.
        client = DraftApiClient(
            ClientSettings(backend_url="http://testserver", allow_draft_contract=True)
        )
        original = HTTP["execution-completed"]
        foreign = deepcopy(original)
        foreign["session_id"] = FOREIGN
        foreign["answer"]["session_id"] = FOREIGN
        token = SecretStr("synthetic-qa-token")
        with patch("httpx.Client.request", return_value=httpx.Response(200, json=foreign)):
            with self.assertRaises(ClientError):
                client.execution(
                    token,
                    UUID(original["execution"]["execution_id"]),
                    UUID(original["session_id"]),
                )


class IndependentSessionAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1700000000.0
        self.client = TestClient(
            create_app(clock=lambda: self.now), base_url="https://photoagent-dev.home.arpa"
        )
        self.addCleanup(self.client.close)
        context = self.client.get("/f01/browser/context").json()
        self.headers = {
            "Origin": "https://photoagent-dev.home.arpa",
            "X-F01-CSRF": context["csrf_token"],
        }
        response = self.client.post(
            "/f01/browser/create", json={"request_id": FOREIGN}, headers=self.headers
        )
        self.assertEqual(response.status_code, 204)
        self.bearer = {"Authorization": f"Bearer {self.client.cookies.get(COOKIE)}"}
        self.before = self.client.get("/f01/internal/snapshot", headers=self.bearer).json()

    def test_malformed_actions_do_not_mutate_session(self) -> None:
        self.now += 10
        for action in ("clear", "opened"):
            for body in ("", "null", "[]", "{", '{"request_id":null}'):
                with self.subTest(action=action, body=body):
                    result = self.client.post(
                        f"/f01/browser/{action}",
                        content=body,
                        headers={**self.headers, "Content-Type": "application/json"},
                    )
                    self.assertEqual(result.status_code, 422)
                    self.assertNotIn("set-cookie", result.headers)
                    after = self.client.get("/f01/internal/snapshot", headers=self.bearer)
                    self.assertEqual(after.json(), self.before)

    def test_exact_ttl_boundary_and_empty_clear(self) -> None:
        self.now += 43199.999
        self.assertEqual(
            self.client.get("/f01/internal/snapshot", headers=self.bearer).json(), self.before
        )
        self.now = 1700000000.0 + 43200
        body = {"request_id": FOREIGN, "expected_session_id": self.before["session_id"]}
        for action, status in (("opened", 401), ("clear", 204)):
            result = self.client.post(f"/f01/browser/{action}", json=body, headers=self.headers)
            self.assertEqual(result.status_code, status)
        self.assertEqual(
            self.client.get("/f01/internal/snapshot", headers=self.bearer).status_code, 401
        )


if __name__ == "__main__":
    unittest.main()
