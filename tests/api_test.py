"""Проверка жизненного цикла и контрактов через HTTP."""

import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from photo_api.main import create_app
from photo_api.settings import ApiSettings


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = self.enterContext(TestClient(create_app(ApiSettings(max_turns=3))))
        response = self.client.post("/sessions")
        self.assertEqual(response.status_code, 201)
        self.session_id = response.json()["session_id"]

    def send(self, text: str, request_id: str | None = None) -> dict[str, object]:
        response = self.client.post(
            f"/sessions/{self.session_id}/messages",
            json={"request_id": request_id or str(uuid4()), "text": text},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_context_and_confirmation(self) -> None:
        self.assertEqual(self.send("Объясни диафрагму")["topics"], ["theory"])
        self.assertEqual(self.send("Да, продолжай")["reply"], "Утвердительный ответ")
        self.assertEqual(self.send("А почему?")["topics"], ["theory"])
        history = self.client.get(f"/sessions/{self.session_id}").json()["messages"]
        self.assertEqual(len(history), 6)
        self.assertEqual(history[0]["text"], "Объясни диафрагму")

    def test_topics_and_multiple_dispatch(self) -> None:
        result = self.send("Найди студию и объясни глубину резкости")
        self.assertEqual(result["topics"], ["search", "theory"])
        self.assertEqual(result["reply"], "Поиск оборудования или услуг\nТеоретические вопросы")
        self.assertEqual(self.send("Почему на этом кадре смазан фон?")["topics"], ["frame"])
        self.assertEqual(self.send("Привет")["reply"], "Тема не определена")

    def test_session_isolation_and_delete(self) -> None:
        self.send("Объясни выдержку")
        other = self.client.post("/sessions").json()["session_id"]
        self.assertEqual(self.client.get(f"/sessions/{other}").json()["messages"], [])
        self.assertEqual(self.client.delete(f"/sessions/{self.session_id}").status_code, 204)
        self.assertEqual(self.client.delete(f"/sessions/{self.session_id}").status_code, 204)
        self.assertEqual(self.client.get(f"/sessions/{self.session_id}").status_code, 404)
        response = self.client.post(
            f"/sessions/{self.session_id}/messages",
            json={"request_id": str(uuid4()), "text": "Да"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(f"/sessions/{other}").status_code, 200)

    def test_beacon_close(self) -> None:
        response = self.client.post(f"/sessions/{self.session_id}/close")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertEqual(self.client.get(f"/sessions/{self.session_id}").status_code, 404)

    def test_idempotency_and_conflict(self) -> None:
        request_id = str(uuid4())
        first = self.send("Да", request_id)
        self.assertEqual(self.send("Да", request_id), first)
        response = self.client.post(
            f"/sessions/{self.session_id}/messages",
            json={"request_id": request_id, "text": "Найди студию"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.client.get(f"/sessions/{self.session_id}").json()["messages"]), 2)

    def test_invalid_inputs_do_not_change_history(self) -> None:
        for text in ("", "   ", "а" * 4001):
            with self.subTest(length=len(text)):
                response = self.client.post(
                    f"/sessions/{self.session_id}/messages",
                    json={"request_id": str(uuid4()), "text": text},
                )
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get(f"/sessions/{self.session_id}").json()["messages"], [])

    def test_message_limit(self) -> None:
        for _ in range(3):
            self.send("Да")
        response = self.client.post(
            f"/sessions/{self.session_id}/messages",
            json={"request_id": str(uuid4()), "text": "Да"},
        )
        self.assertEqual(response.status_code, 409)

    def test_health_and_openapi(self) -> None:
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        schema = self.client.get("/openapi.json").json()
        operation = schema["paths"]["/sessions/{session_id}/messages"]["post"]
        self.assertTrue({"200", "404", "409", "422"}.issubset(operation["responses"]))
