"""Chrome: поведение компонента F-01 с подменой API; не сквозная приёмка B-02."""

import argparse
import json
import unittest
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Route, expect, sync_playwright

ORIGIN = "https://f01.invalid"
COOKIE = "__Host-photoagent-f01"
SESSION_ID = "00000000-0000-4000-8000-000000000001"
SMOKE_URL: str | None = None


class BrowserProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)
        print(f"Chrome {cls.browser.version}; браузерный API в тестах подменён.")
        root = Path(__file__).resolve().parents[1]
        cls.script = (root / "streamlit-ui/photo_ui/session_probe/browser.js").read_text()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        self.context: BrowserContext = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.live = False
        self.created = 0
        self.opened: list[str] = []
        self.mutations: list[str] = []
        self.fail = False
        self.context.route(f"{ORIGIN}/**", self.route)

    def route(self, route: Route) -> None:
        path = route.request.url.removeprefix(ORIGIN)
        if path == "/component.js":
            route.fulfill(content_type="text/javascript", body=self.script)
        elif path.startswith("/f01/browser/"):
            self.api(route, path.rsplit("/", 1)[-1])
        else:
            route.fulfill(
                content_type="text/html",
                body="""<!doctype html><div id="host"><div data-f01-controls></div></div>
                <script type="module">
                  import mount from '/component.js';
                  const component = {parentElement: document.querySelector('#host'),
                                     data: {timeout_ms: 1000}};
                  let cleanup = mount(component);
                  window.remount = () => { cleanup(); cleanup = mount(component); };
                </script>""",
            )

    def api(self, route: Route, action: str) -> None:
        if self.fail:
            route.fulfill(status=503, body="synthetic-private-error")
            return
        has_cookie = COOKIE in (route.request.header_value("cookie") or "")
        if action == "context":
            route.fulfill(
                content_type="application/json",
                body=json.dumps(
                    {
                        "session_id": SESSION_ID if self.live and has_cookie else None,
                        "csrf_token": "synthetic-csrf",
                    }
                ),
            )
            return
        self.assertEqual(route.request.method, "POST")
        self.assertEqual(route.request.header_value("x-f01-csrf"), "synthetic-csrf")
        self.mutations.append(action)
        headers = {}
        if action == "create":
            if not (self.live and has_cookie):
                self.created += 1
            self.live = True
            headers["Set-Cookie"] = (
                f"{COOKIE}=synthetic-browser-token; HttpOnly; Secure; SameSite=Lax; Path=/"
            )
        elif action == "opened":
            self.opened.append(route.request.post_data_json["request_id"])
        elif action == "clear":
            self.live = False
            headers["Set-Cookie"] = f"{COOKIE}=; Max-Age=0; Secure; HttpOnly; Path=/"
        route.fulfill(status=204, headers=headers)

    def page(self) -> Page:
        page = self.context.new_page()
        page.goto(ORIGIN)
        expect(page.get_by_role("button", name="Проверить связь")).to_be_enabled()
        return page

    def create(self, page: Page) -> None:
        page.get_by_role("button", name="Начать тестовую сессию").click()
        expect(page.get_by_role("status")).to_contain_text("Браузер видит живую сессию")

    def test_refresh_registers_once_but_remount_does_not(self) -> None:
        page = self.page()
        self.create(page)
        self.assertEqual(self.opened, [])
        page.reload()
        expect(page.get_by_role("status")).to_contain_text("Браузер видит живую сессию")
        self.assertEqual(len(self.opened), 1)
        page.evaluate("window.remount()")
        expect(page.get_by_role("status")).to_contain_text("Браузер видит живую сессию")
        page.get_by_role("button", name="Проверить связь").click()
        expect(page.get_by_role("status")).to_contain_text("Браузер видит живую сессию")
        self.assertEqual(len(self.opened), 1)
        self.assertNotIn(COOKIE, page.evaluate("document.cookie"))

    def test_two_first_tabs_create_only_one_session(self) -> None:
        first, second = self.page(), self.page()
        # evaluate запускает обработчик без ожидания завершения fetch другой вкладки.
        first.evaluate("document.querySelector('[data-action=create]').click()")
        second.evaluate("document.querySelector('[data-action=create]').click()")
        for page in (first, second):
            expect(page.get_by_role("status")).to_contain_text("Браузер видит живую сессию")
        self.assertEqual(self.created, 1)
        self.assertEqual(len(self.context.cookies()), 1)

    def test_clear_requires_confirmation_and_does_not_recreate(self) -> None:
        page = self.page()
        self.create(page)
        page.once("dialog", lambda dialog: dialog.dismiss())
        page.get_by_role("button", name="Очистить тестовую сессию").click()
        self.assertTrue(self.live)
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Очистить тестовую сессию").click()
        expect(page.get_by_role("status")).to_contain_text("Живой сессии нет")
        self.assertFalse(self.live)
        self.assertEqual(self.created, 1)
        self.assertEqual(self.context.cookies(), [])

    def test_api_failure_is_safe_and_retry_is_explicit(self) -> None:
        self.fail = True
        page = self.page()
        expect(page.get_by_role("status")).to_contain_text("операция не подтверждена")
        self.assertNotIn("synthetic-private-error", page.locator("body").inner_text())
        self.assertEqual(self.mutations, [])
        self.fail = False
        page.get_by_role("button", name="Проверить связь").click()
        expect(page.get_by_role("status")).to_contain_text("Живой сессии нет")
        self.assertEqual(self.mutations, [])

    def test_live_streamlit_shell(self) -> None:
        if SMOKE_URL is None:
            self.skipTest("Для проверки живой оболочки передайте --ui-url")
        page = self.context.new_page()
        page.goto(SMOKE_URL)
        heading = page.get_by_role("heading", name="F-01 · Проверка браузерной сессии")
        expect(heading).to_be_visible()
        expect(page.get_by_role("button", name="Проверить связь")).to_be_visible()
        expect(page.get_by_role("button", name="Начать тестовую сессию")).to_be_visible()
        expect(page.get_by_role("button", name="Записать тестовую отметку")).to_be_visible()
        expect(page.get_by_role("button", name="Очистить тестовую сессию")).to_be_visible()
        expect(page.locator('[data-testid="stException"]')).to_have_count(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui-url", help="Дополнительно проверить оболочку работающего Streamlit")
    arguments, remaining = parser.parse_known_args()
    SMOKE_URL = arguments.ui_url
    unittest.main(argv=[__file__, *remaining])
