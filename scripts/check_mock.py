"""HTTP-проверки D-05; запускаются явно при работающем тестовом Compose."""

import json
import unittest

import httpx


class MockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = httpx.Client(base_url="http://127.0.0.1:4000", trust_env=False, timeout=5)
        self.addCleanup(self.client.close)
        self.client.post("/__test/reset").raise_for_status()

    def request(self, scenario: str, timeout: float = 5) -> httpx.Response:
        return self.client.post(
            "/v1/chat/completions",
            json={
                "model": scenario,
                "messages": [
                    {"role": "user", "content": "Первый синтетический запрос"},
                    {"role": "assistant", "content": "Синтетический ответ"},
                    {"role": "user", "content": "Последний синтетический запрос"},
                ],
            },
            timeout=timeout,
        )

    def test_echo_and_usage(self) -> None:
        response = self.request("echo")
        response.raise_for_status()
        result = response.json()
        self.assertEqual(
            result["choices"][0]["message"]["content"], "Последний синтетический запрос"
        )
        self.assertEqual(
            result["usage"], {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        )

    def test_fixture_and_reset(self) -> None:
        first = self.request("fixture").json()
        second = self.request("fixture").json()
        self.assertEqual(first, second)
        self.assertIn("claims", json.loads(first["choices"][0]["message"]["content"]))
        self.assertEqual(self.client.get("/__test/state").json()["calls"], 2)
        self.assertEqual(self.client.post("/__test/reset").json()["calls"], 0)

    def test_failures(self) -> None:
        response = self.request("rate-limit")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "1")
        self.assertEqual(self.request("server-error").status_code, 503)
        self.assertEqual(self.client.get("/__test/state").json()["calls"], 2)

    def test_invalid_payloads(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            self.request("malformed-json").json()
        self.assertNotIn("usage", self.request("missing-usage").json())
        self.assertEqual(self.request("invalid-usage").json()["usage"]["prompt_tokens"], -1)
        self.assertEqual(self.request("length").json()["choices"][0]["finish_reason"], "length")

    def test_timeout_is_counted_once(self) -> None:
        with self.assertRaises(httpx.ReadTimeout):
            self.request("delay", timeout=0.1)
        self.assertEqual(self.client.get("/__test/state").json()["calls"], 1)

    def test_unknown_model_cannot_route_to_provider(self) -> None:
        self.assertEqual(self.request("openai/live-model").status_code, 422)
        self.assertEqual(self.client.get("/__test/state").json()["calls"], 0)


if __name__ == "__main__":
    unittest.main()
