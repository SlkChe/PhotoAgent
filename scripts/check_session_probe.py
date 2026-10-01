"""B-02: живой Chrome → HTTPS → Streamlit → отдельный экспериментальный API."""

import tempfile
import unittest
from uuid import uuid4

import httpx
from playwright.sync_api import Page, Route, expect, sync_playwright

ORIGIN = "https://photoagent-dev.home.arpa"
URL = ORIGIN + "/f01/ui/"
COOKIE = "__Host-photoagent-f01"


class LiveSessionProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="photoagent-b02-")
        self.addCleanup(self.directory.cleanup)
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.context = self.playwright.chromium.launch_persistent_context(
            self.directory.name,
            channel="chrome",
            headless=True,
        )
        self.addCleanup(self.context.close)
        self.client = httpx.Client(base_url="http://127.0.0.1:8001", trust_env=False, timeout=5)
        self.addCleanup(self.client.close)

    def page(self) -> Page:
        page = self.context.new_page()
        page.goto(URL)
        expect(page.get_by_role("button", name="Начать тестовую сессию")).to_be_enabled()
        return page

    def create(self, page: Page) -> None:
        page.get_by_role("button", name="Начать тестовую сессию").click()
        expect(
            page.get_by_text("Токен из cookie принят API через серверный HTTP-клиент.")
        ).to_be_visible(timeout=15000)

    def snapshot(self) -> dict[str, object]:
        cookie = next(cookie for cookie in self.context.cookies() if cookie["name"] == COOKIE)
        result = self.client.get(
            "/f01/internal/snapshot", headers={"Authorization": f"Bearer {cookie['value']}"}
        )
        result.raise_for_status()
        return result.json()

    def test_cookie_marker_refresh_reconnect(self) -> None:
        page = self.context.new_page()
        page.add_init_script("""(() => {
            const Original = window.WebSocket;
            window.f01TestSockets = [];
            window.WebSocket = new Proxy(Original, {construct(target, args) {
                const socket = Reflect.construct(target, args);
                window.f01TestSockets.push(socket);
                return socket;
            }});
        })();""")
        sockets: list[str] = []
        page.on("websocket", lambda socket: sockets.append(socket.url))
        page.goto(URL)
        expect(page.get_by_role("button", name="Начать тестовую сессию")).to_be_enabled()
        self.create(page)
        cookie = next(cookie for cookie in self.context.cookies() if cookie["name"] == COOKIE)
        self.assertTrue(cookie["httpOnly"] and cookie["secure"])
        self.assertEqual(cookie["sameSite"], "Lax")
        self.assertNotIn(COOKIE, page.evaluate("document.cookie"))
        page.get_by_role("button", name="Записать тестовую отметку").click()
        expect(page.get_by_text("Тестовая отметка сохранена.", exact=False)).to_be_visible()
        before = self.snapshot()
        page.reload()
        expect(
            page.get_by_text("Токен из cookie принят API через серверный HTTP-клиент.")
        ).to_be_visible()
        expect(page.get_by_text("Браузер видит живую сессию.", exact=False)).to_be_visible()
        after = self.snapshot()
        self.assertEqual(after["session_id"], before["session_id"])
        self.assertEqual(after["marker"], "Проверка F-01")
        self.assertGreater(after["last_activity_at"], before["last_activity_at"])
        connections = len(sockets)
        self.assertGreater(connections, 0)
        self.context.set_offline(True)
        page.evaluate("window.f01TestSockets.forEach(socket => socket.close())")
        page.wait_for_timeout(4000)
        self.context.set_offline(False)
        page.wait_for_timeout(8000)
        expect(
            page.get_by_text("Токен из cookie принят API через серверный HTTP-клиент.")
        ).to_be_visible()
        self.assertGreater(len(sockets), connections, "WSS не переподключился")
        self.assertEqual(self.snapshot(), after)
        self.assertEqual(page.locator('[data-testid="stException"]').count(), 0)

    def test_two_first_tabs_clear_and_new_session(self) -> None:
        first, second = self.page(), self.page()
        for page in (first, second):
            page.get_by_role("button", name="Начать тестовую сессию").evaluate(
                "button => button.click()"
            )
        for page in (first, second):
            expect(
                page.get_by_text("Токен из cookie принят API через серверный HTTP-клиент.")
            ).to_be_visible(timeout=15000)
        original = self.snapshot()["session_id"]
        for page in (first, second):
            self.assertIn(original, page.locator('[data-testid="stJson"]').inner_text())
        first.once("dialog", lambda dialog: dialog.accept())
        first.get_by_role("button", name="Очистить тестовую сессию").click()
        expect(
            second.get_by_text("Сессия отозвана или истекла. Локальная копия очищена.")
        ).to_be_visible(timeout=10000)
        expect(first.get_by_role("button", name="Начать тестовую сессию")).to_be_enabled()
        self.create(first)
        self.assertNotEqual(original, self.snapshot()["session_id"])

    def test_allowlist_and_csrf(self) -> None:
        page = self.page()
        self.create(page)
        before = self.snapshot()
        for path in ("/f01/internal/snapshot", "/f01/unknown"):
            self.assertEqual(page.evaluate("async path => (await fetch(path)).status", path), 404)
        for action, body in (
            ("clear", {"request_id": str(uuid4()), "expected_session_id": before["session_id"]}),
            ("marker", {"marker": "bad"}),
            ("create", {"request_id": str(uuid4())}),
            ("opened", {"request_id": str(uuid4()), "expected_session_id": before["session_id"]}),
        ):
            result = page.evaluate(
                """async ({action, body}) => (await fetch(
                '/f01/browser/' + action, {method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify(body)})).status""",
                {"action": action, "body": body},
            )
            self.assertEqual(result, 403)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(
            page.evaluate("async () => (await fetch('/f01/browser/context')).status"), 200
        )

    def browser_action(self, page: Page, action: str, body: dict[str, str]) -> int:
        """Отправляет настоящее действие через ingress; токены остаются в браузере."""
        return page.evaluate(
            """async ({action, body}) => {
                const context = await (await fetch('/f01/browser/context')).json();
                const response = await fetch('/f01/browser/' + action, {method:'POST',
                    headers:{'Content-Type':'application/json','X-F01-CSRF':context.csrf_token},
                    body:JSON.stringify(body)});
                return response.status;
            }""",
            {"action": action, "body": body},
        )

    def replace_session(self, page: Page, previous: str) -> dict[str, object]:
        """Меняет сессию во второй вкладке, сохраняя общую браузерную cookie."""
        self.assertEqual(
            self.browser_action(
                page,
                "clear",
                {
                    "request_id": str(uuid4()),
                    "expected_session_id": previous,
                },
            ),
            204,
        )
        self.assertEqual(self.browser_action(page, "create", {"request_id": str(uuid4())}), 204)
        self.assertEqual(self.browser_action(page, "marker", {"marker": "S2 preserved"}), 204)
        return self.snapshot()

    def test_stale_confirm_waiting_for_lock_cannot_clear_new_session(self) -> None:
        first = self.page()
        self.create(first)
        second = self.page()
        expect(second.get_by_text("Браузер видит живую сессию.", exact=False)).to_be_visible()
        original = self.snapshot()["session_id"]
        second.evaluate("""() => {
            window.b15Locked = false;
            navigator.locks.request('photoagent.f01.session', () => new Promise(resolve => {
                window.b15Release = resolve; window.b15Locked = true;
            }));
        }""")
        second.wait_for_function("window.b15Locked")
        first.once("dialog", lambda dialog: dialog.accept())
        first.get_by_role("button", name="Очистить тестовую сессию").click()
        first.wait_for_function(
            "window[Symbol.for('photoagent.f01.document')].pendingClear !== null"
        )
        before = self.replace_session(second, original)
        second.evaluate("window.b15Release()")
        expect(first.get_by_text("Сессия изменилась.", exact=False)).to_be_visible()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(
            self.browser_action(
                first,
                "opened",
                {
                    "request_id": str(uuid4()),
                    "expected_session_id": original,
                },
            ),
            409,
        )
        self.assertEqual(self.snapshot(), before)
        first.get_by_role("button", name="Обновить подключение").click()
        expect(first.get_by_role("button", name="Очистить тестовую сессию")).to_be_enabled()
        first.once("dialog", lambda dialog: dialog.dismiss())
        first.get_by_role("button", name="Очистить тестовую сессию").click()
        self.assertEqual(self.snapshot(), before)
        first.once("dialog", lambda dialog: dialog.accept())
        first.get_by_role("button", name="Очистить тестовую сессию").click()
        expect(first.get_by_text("Живой сессии нет.", exact=False)).to_be_visible()

    def test_lost_clear_response_retry_keeps_original_intent(self) -> None:
        first = self.page()
        self.create(first)
        second = self.page()
        expect(second.get_by_text("Браузер видит живую сессию.", exact=False)).to_be_visible()
        original = self.snapshot()["session_id"]
        sent: list[dict[str, str]] = []

        def lose_response(route: Route) -> None:
            sent.append(route.request.post_data_json)
            result = route.fetch()
            self.assertEqual(result.status, 204)
            # Результат уже применён сервером; первая вкладка не получает подтверждения.
            self.assertEqual(
                self.browser_action(second, "create", {"request_id": str(uuid4())}), 204
            )
            route.abort("failed")

        first.route("**/f01/browser/clear", lose_response, times=1)
        first.once("dialog", lambda dialog: dialog.accept())
        first.get_by_role("button", name="Очистить тестовую сессию").click()
        expect(first.get_by_text("Операция не подтверждена.", exact=False)).to_be_visible()
        before = self.snapshot()
        self.assertNotEqual(before["session_id"], original)
        pending = first.evaluate("window[Symbol.for('photoagent.f01.document')].pendingClear")
        self.assertEqual(pending, sent[0])
        self.assertEqual(pending["expected_session_id"], original)
        with first.expect_request("**/f01/browser/clear") as retry:
            first.get_by_role("button", name="Повторить очистку").click()
        self.assertEqual(retry.value.post_data_json, sent[0])
        expect(first.get_by_text("Сессия изменилась.", exact=False)).to_be_visible()
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
