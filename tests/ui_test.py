"""Проверка действий Streamlit с настоящим API через тестовый транспорт."""

import os
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from photo_api.main import create_app
from photo_ui.api_client import ApiError
from shared.contracts import MessageRequest, MessageResponse, SessionResponse


class TestApiAdapter:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.lose_response = False

    def create_session(self) -> SessionResponse:
        return SessionResponse.model_validate(self.client.post("/sessions").json())

    def delete_session(self, session_id: UUID) -> None:
        self.client.delete(f"/sessions/{session_id}")

    def heartbeat(self, session_id: UUID) -> None:
        response = self.client.post(f"/sessions/{session_id}/heartbeat")
        if response.status_code == 404:
            raise ApiError("Сессия завершена. Начните новый чат.", 404)

    def send(self, session_id: UUID, request: MessageRequest) -> MessageResponse:
        response = self.client.post(
            f"/sessions/{session_id}/messages",
            json=request.model_dump(mode="json"),
        )
        if self.lose_response:
            self.lose_response = False
            raise ApiError("Соединение прервано")
        return MessageResponse.model_validate(response.json())


class UiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = self.enterContext(TestClient(create_app()))
        self.adapter = TestApiAdapter(self.client)
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "PHOTO_UI_BACKEND_URL": "http://testserver",
                    "PHOTO_UI_PUBLIC_BACKEND_URL": "http://testserver",
                },
            )
        )
        self.enterContext(patch("photo_ui.app.ApiClient", return_value=self.adapter))
        self.enterContext(patch("photo_ui.app.mount_close_handler"))
        self.app = AppTest.from_file("../streamlit-ui/app.py", default_timeout=10).run()
        self.assertFalse(self.app.exception)

    def test_send_and_new_chat(self) -> None:
        old_id = self.app.session_state.chat.session_id
        self.app.chat_input[0].set_value("Объясни диафрагму").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.chat_message), 2)
        self.assertEqual(self.app.session_state.chat.messages[-1].text, "Теоретические вопросы")
        self.app.button(key="new_chat").click().run()
        self.assertFalse(self.app.exception)
        self.assertNotEqual(self.app.session_state.chat.session_id, old_id)
        self.assertEqual(self.app.session_state.chat.messages, [])
        self.assertEqual(self.client.get(f"/sessions/{old_id}").status_code, 404)

    def test_retry_after_lost_response_does_not_duplicate(self) -> None:
        self.adapter.lose_response = True
        self.app.chat_input[0].set_value("Найди студию").run()
        self.assertIsNotNone(self.app.session_state.chat.pending)
        retry = next(button for button in self.app.button if button.label == "Повторить отправку")
        retry.click().run()
        self.assertFalse(self.app.exception)
        session_id = self.app.session_state.chat.session_id
        self.assertEqual(len(self.client.get(f"/sessions/{session_id}").json()["messages"]), 2)
        self.assertEqual(len(self.app.session_state.chat.messages), 2)

    def test_separate_browser_session_starts_empty(self) -> None:
        self.app.chat_input[0].set_value("Да").run()
        other = AppTest.from_file("../streamlit-ui/app.py", default_timeout=10).run()
        self.assertFalse(other.exception)
        self.assertNotEqual(
            self.app.session_state.chat.session_id, other.session_state.chat.session_id
        )
        self.assertEqual(other.session_state.chat.messages, [])

    def test_delete_failure_preserves_current_chat(self) -> None:
        self.app.chat_input[0].set_value("Да").run()
        session_id = self.app.session_state.chat.session_id
        with patch.object(self.adapter, "delete_session", side_effect=ApiError("Нет связи")):
            self.app.button(key="new_chat").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state.chat.session_id, session_id)
        self.assertEqual(len(self.app.session_state.chat.messages), 2)
        self.assertEqual(self.app.warning[0].value, "Нет связи")

    def test_expired_session_disables_input(self) -> None:
        session_id = self.app.session_state.chat.session_id
        self.client.delete(f"/sessions/{session_id}")
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertTrue(self.app.chat_input[0].disabled)
        self.app.button(key="new_chat").click().run()
        self.assertFalse(self.app.chat_input[0].disabled)

    def test_connection_failure_can_be_retried(self) -> None:
        with patch.object(self.adapter, "create_session", side_effect=ApiError("Нет связи")):
            other = AppTest.from_file("../streamlit-ui/app.py", default_timeout=10).run()
        self.assertFalse(other.exception)
        self.assertTrue(other.error)
        retry = next(button for button in other.button if button.label == "Подключиться снова")
        retry.click().run()
        self.assertFalse(other.exception)
        self.assertIsNotNone(other.session_state.chat.session_id)
