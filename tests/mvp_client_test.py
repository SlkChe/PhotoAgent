"""Совместимость нового F-02 с B-01; сетевые ответы подменены, runtime ещё отсутствует."""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import httpx
from pydantic import SecretStr

from photo_ui.mvp_client.client import DraftApiClient
from photo_ui.mvp_client.state import DeliveryState
from photo_ui.mvp_client.transport import ClientError, ClientSettings
from shared.http_draft.operations import MessageRequest
from shared.http_draft.session import SessionSnapshot


class MvpClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.examples = {
            item["id"]: item["payload"]
            for item in json.loads(Path("docs/mvp-1/http-contract-examples.json").read_text())[
                "examples"
            ]
        }
        self.client = DraftApiClient(
            ClientSettings(
                backend_url="http://testserver",
                allow_draft_contract=True,
            )
        )
        self.token = SecretStr("synthetic-test-token")

    def test_snapshot_compatibility_and_bearer_transport(self) -> None:
        body = self.examples["snapshot-completed"]
        with patch("httpx.Client.request", return_value=httpx.Response(200, json=body)) as send:
            result = self.client.snapshot(self.token)
        self.assertEqual(result, SessionSnapshot.model_validate(body))
        self.assertEqual(send.call_count, 1)
        self.assertEqual(
            send.call_args.kwargs["headers"], {"Authorization": "Bearer synthetic-test-token"}
        )
        with patch(
            "httpx.Client.request",
            return_value=httpx.Response(
                200,
                json={**body, "contract_version": "unknown"},
            ),
        ):
            with self.assertRaises(ClientError) as caught:
                self.client.snapshot(self.token)
        self.assertEqual(caught.exception.code, "incompatible_response")

    def test_send_accepts_contract_but_rejects_foreign_request(self) -> None:
        request = MessageRequest.model_validate(self.examples["send-message"])
        accepted = self.examples["accepted"]
        session_id = UUID(accepted["session_id"])
        with patch("httpx.Client.request", return_value=httpx.Response(202, json=accepted)):
            self.assertEqual(
                self.client.send(self.token, request, session_id).request_id, request.request_id
            )
        foreign = {**accepted, "session_id": "00000000-0000-4000-8000-000000000099"}
        with patch("httpx.Client.request", return_value=httpx.Response(202, json=foreign)):
            with self.assertRaises(ClientError) as caught:
                self.client.send(self.token, request, session_id)
        self.assertEqual(caught.exception.code, "request_mismatch")

    def test_poll_checks_session_and_execution_independently(self) -> None:
        original = self.examples["execution-completed"]
        session_id = UUID(original["session_id"])
        execution_id = UUID(original["execution"]["execution_id"])
        other_id = "00000000-0000-4000-8000-000000000099"
        for changed, code in (
            (None, None),
            ("session", "session_mismatch"),
            ("execution", "execution_mismatch"),
        ):
            with self.subTest(changed=changed):
                body = deepcopy(original)
                if changed == "session":
                    body["session_id"] = body["answer"]["session_id"] = other_id
                elif changed == "execution":
                    body["execution"]["execution_id"] = other_id
                    body["answer"]["execution_id"] = other_id
                with patch("httpx.Client.request", return_value=httpx.Response(200, json=body)):
                    if code is None:
                        result = self.client.execution(self.token, execution_id, session_id)
                        self.assertEqual(result.session_id, session_id)
                    else:
                        with self.assertRaises(ClientError) as caught:
                            self.client.execution(self.token, execution_id, session_id)
                        self.assertEqual(caught.exception.code, code)

    def test_lost_delivery_restores_without_second_generation(self) -> None:
        empty = SessionSnapshot.model_validate(self.examples["snapshot-empty"])
        state = DeliveryState()
        state.restore(empty)
        request = state.prepare("Что такое диафрагма?")
        state.failure(ClientError("network"))
        with self.assertRaises(ClientError):
            state.retry()
        self.assertEqual(state.draft, request.text)
        state.restore(empty)
        self.assertEqual(state.retry(), request)
        body = json.loads(json.dumps(self.examples["snapshot-in-progress"]))
        body["session_id"] = str(empty.session_id)
        body["executions"][0]["request_id"] = str(request.request_id)
        body["messages"][0]["request_id"] = str(request.request_id)
        body["revision"] = empty.revision + 1
        state.restore(SessionSnapshot.model_validate(body))
        self.assertIsNone(state.pending_json)
        self.assertEqual(state.draft, "")
        with self.assertRaises(ClientError):
            state.retry()
        state.failure(ClientError("unavailable", 401))
        self.assertIsNone(state.snapshot)

    def test_draft_disabled_and_timeout_never_retry_implicitly(self) -> None:
        disabled = DraftApiClient(ClientSettings(backend_url="http://testserver"))
        with patch("httpx.Client.request") as send:
            with self.assertRaises(ClientError):
                disabled.snapshot(self.token)
            send.assert_not_called()
        with patch("httpx.Client.request", side_effect=httpx.ReadTimeout("private")) as send:
            with self.assertRaises(ClientError) as caught:
                self.client.snapshot(self.token)
            self.assertEqual(send.call_count, 1)
        self.assertEqual(caught.exception.kind, "network")
        self.assertNotIn("private", str(caught.exception))
