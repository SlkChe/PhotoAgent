"""Лимиты LLM читаются из окружения и согласованы между уровнями."""

import unittest
from unittest.mock import patch

from pydantic import ValidationError

from photo_api.settings import ApiSettings


class SettingsTest(unittest.TestCase):
    def test_approved_defaults(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            settings = ApiSettings()
        self.assertEqual(settings.llm_project_tokens_per_24h, 100000)
        self.assertEqual(settings.llm_project_tokens_per_minute, 5000)
        self.assertEqual(settings.llm_project_tokens_per_request, 5000)
        self.assertEqual(settings.llm_session_max_requests, 100)
        self.assertEqual(settings.llm_session_tokens_per_request, 1500)
        self.assertEqual(settings.llm_session_tokens_per_minute, 3000)
        self.assertEqual(settings.llm_estimated_chars_per_token, 3)

    def test_deployment_environment_overrides_limits(self) -> None:
        values = {
            "PHOTO_API_LLM_SESSION_MAX_REQUESTS": "20",
            "PHOTO_API_LLM_SESSION_TOKENS_PER_REQUEST": "800",
            "PHOTO_API_LLM_SESSION_TOKENS_PER_MINUTE": "2000",
        }
        with patch.dict("os.environ", values, clear=True):
            settings = ApiSettings()
        self.assertEqual(settings.llm_session_max_requests, 20)
        self.assertEqual(settings.llm_session_tokens_per_request, 800)
        self.assertEqual(settings.llm_session_tokens_per_minute, 2000)

    def test_invalid_or_inconsistent_limits(self) -> None:
        cases = [
            {"llm_session_max_requests": 0},
            {"llm_estimated_chars_per_token": -1},
            {"llm_session_tokens_per_request": 5001},
            {"llm_session_tokens_per_minute": 5001},
            {"llm_session_tokens_per_request": 3001},
            {"llm_project_tokens_per_24h": 1000},
        ]
        with patch.dict("os.environ", {}, clear=True):
            for values in cases:
                with self.subTest(values=values), self.assertRaises(ValidationError):
                    ApiSettings(**values)

    def test_invalid_configuration_does_not_echo_value(self) -> None:
        with patch.dict(
            "os.environ",
            {"PHOTO_API_LLM_SESSION_MAX_REQUESTS": "invalid-sensitive-value"},
            clear=True,
        ):
            with self.assertRaises(ValidationError) as raised:
                ApiSettings()
        self.assertNotIn("invalid-sensitive-value", str(raised.exception))
