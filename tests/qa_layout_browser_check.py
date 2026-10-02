"""Независимая ранняя проверка F-07 на Streamlit preview, без API/LLM."""

import json
import unittest
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ARTIFACTS = Path("docs/mvp-1/qa-artifacts/f07")
URL = "http://127.0.0.1:8504"


class LayoutBrowserAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)
        cls.metadata: list[dict[str, object]] = []

    @classmethod
    def tearDownClass(cls) -> None:
        (ARTIFACTS / "environment.json").write_text(
            json.dumps(cls.metadata, ensure_ascii=False, indent=2) + "\n"
        )
        cls.browser.close()
        cls.playwright.stop()

    def page(self, width: int = 1280, height: int = 720) -> Page:
        context = self.browser.new_context(
            viewport={"width": width, "height": height},
            screen={"width": width, "height": height},
            device_scale_factor=1,
        )
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(5000)
        page.goto(URL)
        expect(page.locator(".shell")).to_be_visible(timeout=20000)
        self.metadata.append(
            {
                "test": self.id(),
                "browser": self.browser.version,
                "headless": True,
                "physical_display": "not measured; screen emulated",
                "metrics": page.evaluate("""() => ({width: innerWidth, height: innerHeight,
                    dpr: devicePixelRatio, scale: visualViewport.scale,
                    screen: {width: screen.width, height: screen.height}})"""),
            }
        )
        return page

    def scenario(self, page: Page, label: str) -> None:
        page.locator('[data-testid="stSelectbox"]').get_by_role("combobox").click()
        page.get_by_role("option", name=label, exact=True).click()
        if label != "Новый диалог":
            expect(page.locator(".message")).to_have_count(24)

    def test_viewport_matrix(self) -> None:
        for width, height in ((1280, 720), (1920, 1080), (3840, 2160), (360, 800), (390, 844)):
            with self.subTest(width=width, height=height):
                page = self.page(width, height)
                self.scenario(page, "Длинный диалог")
                dimensions = page.locator(".shell").evaluate("""e => ({
                    width:e.clientWidth, scroll:e.scrollWidth,
                    bottom:e.getBoundingClientRect().bottom,
                    sendBottom:e.querySelector('.send').getBoundingClientRect().bottom})""")
                self.assertLessEqual(dimensions["scroll"], dimensions["width"])
                self.assertLessEqual(dimensions["sendBottom"], height + 1)
                page.screenshot(path=str(ARTIFACTS / f"layout-{width}x{height}.png"))
                expect(page.locator('[data-testid="stException"]')).to_have_count(0)

    def test_overlay_focus_draft_and_no_send(self) -> None:
        page = self.page(390, 844)
        self.scenario(page, "Длинный диалог")
        prompt = page.locator("textarea")
        prompt.fill("Незавершённый вопрос QA")
        menu = page.get_by_role("button", name="Меню", exact=True)
        sources = page.get_by_role("button", name="Источники · 12", exact=True)
        menu.click()
        expect(page.locator(".menu")).to_have_attribute("aria-hidden", "false")
        expect(page.locator(".conversation")).to_have_attribute("inert", "")
        expect(page.get_by_role("button", name="Закрыть меню")).to_be_focused()
        for _ in range(12):
            page.keyboard.press("Tab")
            self.assertTrue(
                page.locator(".shell").evaluate("""e => {
                const a=e.getRootNode().activeElement;
                return e.contains(a) && !a.closest('[inert]'); }""")
            )
        sources.click()
        expect(page.locator(".menu")).to_have_attribute("aria-hidden", "true")
        expect(page.locator(".sources")).to_have_attribute("aria-hidden", "false")
        page.screenshot(path=str(ARTIFACTS / "sources-mobile.png"))
        page.keyboard.press("Escape")
        expect(sources).to_be_focused()
        expect(prompt).to_have_value("Незавершённый вопрос QA")
        expect(page.locator(".message")).to_have_count(24)

    def test_input_growth_enter_and_explicit_send(self) -> None:
        page = self.page()
        prompt = page.locator("textarea")
        short = prompt.evaluate("e => e.clientHeight")
        prompt.fill("\n".join(f"строка {i}" for i in range(12)))
        large = prompt.evaluate("""e => ({height:e.clientHeight, scroll:e.scrollHeight,
            line:parseFloat(getComputedStyle(e).lineHeight),
            padding:parseFloat(getComputedStyle(e).paddingTop)*2})""")
        self.assertGreater(large["height"], short)
        self.assertLessEqual(large["height"], 7 * large["line"] + large["padding"] + 2)
        self.assertGreater(large["scroll"], large["height"])
        prompt.fill("Тестовая строка")
        prompt.press("End")
        prompt.press("Enter")
        expect(prompt).to_have_value("Тестовая строка\n")
        expect(page.locator(".message")).to_have_count(0)
        prompt.press("Control+Enter")
        expect(page.locator(".message")).to_have_count(1)
        expect(prompt).to_have_value("")
        page.wait_for_timeout(500)
        expect(page.locator(".message")).to_have_count(1)

    def test_settings_rerun_keeps_draft_and_scroll(self) -> None:
        page = self.page()
        self.scenario(page, "Длинный диалог")
        feed = page.locator(".feed")
        feed.evaluate("e => { e.scrollTop=250; e.dispatchEvent(new Event('scroll')); }")
        page.locator("textarea").fill("Черновик перед настройкой")
        page.locator('select[name="detail"]').select_option("detailed")
        expect(page.locator('select[name="detail"]')).to_have_value("detailed")
        page.wait_for_timeout(600)
        expect(page.locator("textarea")).to_have_value("Черновик перед настройкой")
        self.assertAlmostEqual(feed.evaluate("e => e.scrollTop"), 250, delta=2)
        expect(page.locator(".message")).to_have_count(24)

    def test_source_navigation_focuses_original_answer(self) -> None:
        page = self.page(390, 844)
        self.scenario(page, "Длинный диалог")
        page.get_by_role("button", name="Источники · 12").click()
        expect(page.locator(".sources")).to_be_visible()
        card = page.locator(".card").first
        card.locator("summary").click()
        card.get_by_role("button", name="Перейти к диалогу").click()
        expect(page.locator('[data-message="answer-0"]')).to_be_focused()
        expect(page.locator(".sources")).to_have_attribute("aria-hidden", "true")
        expect(page.locator(".conversation")).to_have_attribute("aria-hidden", "false")

    def test_waiting_and_disconnected_disable_input(self) -> None:
        page = self.page()
        for scenario in ("Ожидание", "Нет связи"):
            with self.subTest(scenario=scenario):
                self.scenario(page, scenario)
                expect(page.locator("textarea")).to_be_disabled()
                expect(page.locator(".send")).to_be_disabled()
                expect(page.locator('select[name="detail"]')).to_be_disabled()
                expect(page.locator(".status")).not_to_be_empty()

    def test_send_button_after_draft_settles(self) -> None:
        page = self.page()
        page.locator("textarea").fill("Явная отправка кнопкой QA")
        page.wait_for_timeout(700)
        page.get_by_role("button", name="Отправить", exact=True).click()
        expect(page.locator(".message")).to_have_count(1)
        expect(page.locator("textarea")).to_have_value("")

    def test_narrow_viewport_and_enlarged_text(self) -> None:
        page = self.page(320, 800)
        self.scenario(page, "Длинный диалог")
        page.locator(".shell").evaluate("""e => {
            const style=document.createElement('style');
            style.textContent=':host {font-size:32px}';
            e.getRootNode().append(style);
        }""")
        page.wait_for_timeout(300)
        width = page.locator(".shell").evaluate("e => [e.clientWidth,e.scrollWidth]")
        self.assertLessEqual(width[1], width[0])
        page.screenshot(path=str(ARTIFACTS / "text-200-narrow.png"))


if __name__ == "__main__":
    unittest.main()
