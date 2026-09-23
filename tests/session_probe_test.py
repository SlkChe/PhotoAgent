"""Проверки изоляции токена, ошибок и состояния исследовательского UI F-01."""

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from streamlit.testing.v1 import AppTest

from photo_ui.session_probe.client import ProbeClient, ProbeError, ProbeSettings, ProbeSnapshot

SNAPSHOT = {
    "session_id": "00000000-0000-4000-8000-000000000001",
    "revision": 1,
    "last_activity_at": "2026-09-23T10:00:00Z",
    "expires_at": "2026-09-23T22:00:00Z",
    "marker": "Проверка F-01",
}


class ProbeClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = ProbeClient(ProbeSettings(backend_url="http://testserver"))

    def test_token_only_in_header_and_snapshot_unchanged_on_read(self) -> None:
        with patch("httpx.Client.get", return_value=httpx.Response(200, json=SNAPSHOT)) as get:
            first = self.client.snapshot("synthetic-test-token")
            second = self.client.snapshot("synthetic-test-token")
        self.assertEqual(first, second)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.args, ("http://testserver/f01/internal/snapshot",))
        self.assertEqual(
            get.call_args.kwargs, {"headers": {"Authorization": "Bearer synthetic-test-token"}}
        )
        self.assertNotIn("synthetic-test-token", str(first.diagnostic()))

    def test_revocation_differs_from_missing_route_and_network_failure(self) -> None:
        for status, unavailable in ((401, True), (410, True), (404, False), (503, False)):
            with self.subTest(status=status):
                with patch("httpx.Client.get", return_value=httpx.Response(status)):
                    with self.assertRaises(ProbeError) as caught:
                        self.client.snapshot("synthetic-test-token")
                self.assertEqual(caught.exception.unavailable, unavailable)

    def test_untrusted_errors_and_invalid_response_are_not_displayed(self) -> None:
        for response in (
            httpx.Response(500, text="synthetic-test-token"),
            httpx.Response(200, text="synthetic-test-token"),
            httpx.Response(200, json={**SNAPSHOT, "extra": "synthetic-test-token"}),
            httpx.Response(200, json={**SNAPSHOT, "expires_at": "2026-09-22T10:00:00Z"}),
        ):
            with patch("httpx.Client.get", return_value=response):
                with self.assertRaises(ProbeError) as caught:
                    self.client.snapshot("synthetic-test-token")
                self.assertNotIn("synthetic-test-token", str(caught.exception))

    def test_timeout_does_not_trigger_retry(self) -> None:
        with patch("httpx.Client.get", side_effect=httpx.ReadTimeout("private details")) as get:
            with self.assertRaises(ProbeError) as caught:
                self.client.snapshot("synthetic-test-token")
        self.assertEqual(get.call_count, 1)
        self.assertFalse(caught.exception.unavailable)
        self.assertNotIn("private details", str(caught.exception))


class ProbeUiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(os.environ, {"PHOTO_F01_BACKEND_URL": "http://testserver"}))
        self.enterContext(patch("photo_ui.session_probe.app._BROWSER"))
        path = Path(__file__).resolve().parents[1] / "streamlit-ui/session_probe.py"
        self.app = AppTest.from_file(str(path), default_timeout=10)
        self.cookies = {"__Host-photoagent-f01": "synthetic-test-token"}
        self.enterContext(patch("streamlit.context", SimpleNamespace(cookies=self.cookies)))

    def test_revocation_clears_snapshot(self) -> None:
        with patch("photo_ui.session_probe.app.ProbeClient.snapshot") as snapshot:
            snapshot.return_value = ProbeSnapshot.model_validate(SNAPSHOT)
            self.app.run()
            self.assertFalse(self.app.exception)
            self.assertEqual(len(self.app.json), 1)
            snapshot.side_effect = ProbeError(unavailable=True)
            self.app.run()
        self.assertFalse(self.app.exception)
        self.assertIsNone(self.app.session_state.f01_snapshot)
        self.assertEqual(len(self.app.json), 0)

    def test_network_failure_keeps_last_snapshot_with_warning(self) -> None:
        with patch("photo_ui.session_probe.app.ProbeClient.snapshot") as snapshot:
            snapshot.return_value = ProbeSnapshot.model_validate(SNAPSHOT)
            self.app.run()
            snapshot.side_effect = ProbeError()
            self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.json), 1)
        self.assertIn("устаревшим", self.app.warning[0].value)

    def test_no_cookie_does_not_create_session_or_call_api(self) -> None:
        self.cookies.clear()
        with patch("photo_ui.session_probe.app.ProbeClient.snapshot") as snapshot:
            self.app.run()
        self.assertFalse(self.app.exception)
        snapshot.assert_not_called()
        self.assertEqual(len(self.app.json), 0)


if __name__ == "__main__":
    unittest.main()
