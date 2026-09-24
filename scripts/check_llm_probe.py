"""B-07: независимая проверка черновика через живую HTTP-обвязку LiteLLM."""

import unittest

import httpx

from scripts.llm_probe import LlmProbeError, read_completion


class BackendMockProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = httpx.Client(base_url="http://127.0.0.1:4000", trust_env=False, timeout=5)
        self.addCleanup(self.client.close)
        self.client.post("/__test/reset").raise_for_status()

    def request(self, model: str) -> httpx.Response:
        return self.client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Синтетическая проба"}],
                "max_tokens": 400,
                "stream": False,
            },
        )

    def test_draft_fixture(self) -> None:
        draft, usage = read_completion(self.request("fixture"))
        self.assertEqual(usage.total_tokens, 120)
        self.assertEqual(len(draft.claims), 1)

    def test_failures_are_not_accepted_as_answer_or_retried(self) -> None:
        scenarios = (
            "rate-limit",
            "server-error",
            "malformed-json",
            "length",
            "missing-usage",
            "invalid-usage",
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario), self.assertRaises(LlmProbeError):
                read_completion(self.request(scenario))
        self.assertEqual(self.client.get("/__test/state").json()["calls"], len(scenarios))


if __name__ == "__main__":
    unittest.main()
