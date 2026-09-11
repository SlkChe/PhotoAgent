"""Проверка работающего UI в Chrome и снимки концепта для просмотра."""

import argparse
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page, expect, sync_playwright


def check_chat(page: Page, ui_url: str, output: Path) -> None:
    page.goto(ui_url)
    expect(page.get_by_role("heading", name="Хороший кадр начинается с вопроса.")).to_be_visible()
    page.screenshot(path=str(output / "chat-desktop.png"), full_page=True)
    field = page.get_by_placeholder("Что хочется узнать о фотографии?")
    field.fill("Объясни диафрагму")
    field.press("Enter")
    expect(page.get_by_text("Теоретические вопросы", exact=True)).to_be_visible()
    field.fill("Да, продолжай")
    field.press("Enter")
    expect(page.get_by_text("Утвердительный ответ", exact=True)).to_be_visible()
    page.screenshot(path=str(output / "chat-conversation.png"), full_page=True)
    page.get_by_role("button", name="＋ Новый чат").click()
    expect(page.get_by_role("heading", name="Хороший кадр начинается с вопроса.")).to_be_visible()
    expect(page.get_by_text("Теоретические вопросы", exact=True)).to_have_count(0)


def check_close(page: Page, api_url: str) -> None:
    marker = page.locator('[data-photo-lifecycle="ready"]')
    marker.wait_for(state="attached")
    close_url = marker.get_attribute("data-close-url")
    assert close_url is not None
    session_id = close_url.split("/")[-2]
    with httpx.Client(timeout=5, trust_env=False) as client:
        url = f"{api_url}/sessions/{session_id}"
        assert client.get(url).status_code == 200
        page.goto("about:blank")
        deadline = time.monotonic() + 5
        response = client.get(url)
        while response.status_code == 200 and time.monotonic() < deadline:
            time.sleep(0.1)
            response = client.get(url)
    assert response.status_code == 404, "Закрытие вкладки не удалило сессию"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui-url", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--output", type=Path, default=Path("docs"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(15000)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: print(message.text) if message.type == "error" else None)
        check_chat(page, args.ui_url, args.output)
        try:
            check_close(page, args.api_url)
        except Exception:
            print("Ошибки JavaScript:", errors)
            raise
        assert not errors, errors
        mobile = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        mobile.goto(args.ui_url)
        expect(
            mobile.get_by_role("heading", name="Хороший кадр начинается с вопроса.")
        ).to_be_visible()
        mobile.get_by_role(
            "heading", name="Хороший кадр начинается с вопроса."
        ).scroll_into_view_if_needed()
        mobile.screenshot(path=str(args.output / "chat-mobile.png"), full_page=True)
        check_close(mobile, args.api_url)
        browser.close()
    print("Проверены диалог, новый чат, мобильный экран и удаление при уходе со страницы.")


if __name__ == "__main__":
    main()
