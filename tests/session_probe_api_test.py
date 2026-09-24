"""Проверки реального backend-кандидата B-02, включая управляемые часы."""

import unittest
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from photo_api.session_probe.app import COOKIE, Settings, create_app

ORIGIN = "https://photoagent-dev.home.arpa"


class SessionProbeApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1700000000.0
        self.app = create_app(clock=lambda: self.now)
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.addCleanup(self.client.close)
        self.headers = {"Origin": ORIGIN}
        self.bootstrap()

    def bootstrap(self) -> None:
        response = self.client.get("/f01/browser/context")
        self.assertEqual(response.status_code, 200)
        self.headers["X-F01-CSRF"] = response.json()["csrf_token"]

    def post(self, action: str, body: dict[str, str] | None = None) -> httpx.Response:
        return self.client.post(f"/f01/browser/{action}", json=body or {}, headers=self.headers)

    def create(self, request_id: str | None = None) -> str:
        response = self.post("create", {"request_id": request_id or str(uuid4())})
        self.assertEqual(response.status_code, 204)
        return self.client.cookies.get(COOKIE)

    def snapshot(self, token: str) -> httpx.Response:
        return self.client.get(
            "/f01/internal/snapshot", headers={"Authorization": f"Bearer {token}"}
        )

    def test_lost_response_and_two_create_ids_recover_one_session(self) -> None:
        request_id = str(uuid4())
        token = self.create(request_id)
        self.client.cookies.delete(COOKIE)
        self.assertEqual(self.create(request_id), token)
        self.assertEqual(self.create(), token)
        self.assertEqual(self.snapshot(token).status_code, 200)

    def test_clear_does_not_resurrect_old_request_or_token(self) -> None:
        request_id = str(uuid4())
        token = self.create(request_id)
        self.assertEqual(self.post("clear").status_code, 204)
        self.assertEqual(self.post("clear").status_code, 403)
        self.bootstrap()
        self.assertEqual(self.post("clear").status_code, 204)
        self.bootstrap()
        self.assertEqual(self.snapshot(token).status_code, 401)
        self.assertEqual(self.post("create", {"request_id": request_id}).status_code, 409)
        replacement = self.create()
        self.assertNotEqual(token, replacement)
        self.assertEqual(self.post("create", {"request_id": request_id}).status_code, 409)

    def test_poll_opened_dedup_and_exact_ttl(self) -> None:
        token = self.create()
        initial = self.snapshot(token).json()
        self.now += 10
        self.bootstrap()
        self.assertEqual(self.snapshot(token).json(), initial)
        request_id = str(uuid4())
        self.assertEqual(self.post("opened", {"request_id": request_id}).status_code, 204)
        updated = self.snapshot(token).json()
        self.now += 20
        self.post("opened", {"request_id": request_id})
        self.assertEqual(self.snapshot(token).json(), updated)
        self.now += 43200 - 20
        self.assertEqual(self.snapshot(token).status_code, 401)
        self.assertEqual(self.post("opened", {"request_id": str(uuid4())}).status_code, 401)

    def test_every_mutation_requires_origin_and_bound_csrf(self) -> None:
        token = self.create()
        before = self.snapshot(token).json()
        for action, body in (
            ("create", {"request_id": str(uuid4())}),
            ("opened", {"request_id": str(uuid4())}),
            ("marker", {"marker": "test"}),
            ("clear", {}),
        ):
            for headers in (
                {},
                {"Origin": "https://foreign.invalid"},
                {"Origin": ORIGIN, "X-F01-CSRF": "wrong"},
            ):
                with self.subTest(action=action, headers=list(headers)):
                    response = self.client.post(
                        f"/f01/browser/{action}", json=body, headers=headers
                    )
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.snapshot(token).json(), before)
        with TestClient(self.app, base_url=ORIGIN) as other:
            other.get("/f01/browser/context")
            self.assertEqual(
                other.post("/f01/browser/clear", json={}, headers=self.headers).status_code, 403
            )

    def test_cookie_attributes_bootstrap_and_cross_site(self) -> None:
        response = self.client.get("/f01/browser/context")
        header = response.headers["set-cookie"].lower()
        for attribute in ("secure", "httponly", "samesite=lax", "path=/"):
            self.assertIn(attribute, header)
        for attribute in ("domain=", "expires=", "max-age="):
            self.assertNotIn(attribute, header)
        self.assertEqual(
            self.client.get(
                "/f01/browser/context", headers={"Sec-Fetch-Site": "cross-site"}
            ).status_code,
            403,
        )
        token = self.create()
        self.assertNotIn(token, self.client.get("/f01/browser/context").text)
        self.assertEqual(self.snapshot(str(uuid4())).status_code, 401)

    def test_marker_validation_restart_and_capacity(self) -> None:
        token = self.create()
        self.now += 5
        self.assertEqual(self.post("marker", {"marker": "test"}).status_code, 204)
        self.assertEqual(self.snapshot(token).json()["revision"], 2)
        self.assertEqual(self.post("marker", {"marker": "x" * 101}).status_code, 422)
        with TestClient(create_app(), base_url=ORIGIN) as restarted:
            self.assertEqual(
                restarted.get(
                    "/f01/internal/snapshot", headers={"Authorization": f"Bearer {token}"}
                ).status_code,
                401,
            )
        app = create_app(Settings(max_contexts=1), clock=lambda: self.now)
        with TestClient(app, base_url=ORIGIN) as client:
            self.assertEqual(client.get("/f01/browser/context").status_code, 200)
            client.cookies.clear()
            self.assertEqual(client.get("/f01/browser/context").status_code, 503)
            self.now += 86400
            self.assertEqual(client.get("/f01/browser/context").status_code, 200)
        schema = self.app.openapi()
        self.assertEqual(len(schema["paths"]), 6)
        self.assertIn("401", schema["paths"]["/f01/internal/snapshot"]["get"]["responses"])
