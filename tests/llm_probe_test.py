"""Проверка компактного исследовательского черновика B-07 без облачных вызовов."""

import json
import unittest
from pathlib import Path

import httpx

from scripts.llm_probe import Draft, LlmProbeError, estimate_input, groq_payload, read_completion


class LlmProbeTest(unittest.TestCase):
    def test_fixture_and_budget(self) -> None:
        value = Path("tests/fixtures/llm-draft.json").read_text()
        Draft.model_validate_json(value).check_evidence({"synthetic-evidence-1"})
        self.assertLessEqual(estimate_input(groq_payload()) + 400, 1500)

    def test_invalid_evidence_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Draft(
                text="Ответ", claims=[{"text": "Ответ", "evidence_ids": ["invented"]}]
            ).check_evidence({"e1"})

    def test_invalid_usage_and_truncated_output_are_rejected(self) -> None:
        body = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": Path("tests/fixtures/llm-draft.json").read_text()},
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }
        self.assertEqual(read_completion(httpx.Response(200, json=body))[1].total_tokens, 120)
        for usage in (
            None,
            {},
            {"prompt_tokens": -1},
            {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 121},
        ):
            broken = {**body, "usage": usage}
            with self.assertRaises(LlmProbeError):
                read_completion(httpx.Response(200, json=broken))
        body["choices"][0]["finish_reason"] = "length"
        with self.assertRaises(LlmProbeError):
            read_completion(httpx.Response(200, content=json.dumps(body)))
