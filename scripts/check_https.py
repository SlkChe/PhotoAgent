"""Проверка TLS, ограниченных маршрутов и чата через WebSocket Dev/Stage."""

import argparse
import ssl
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=443)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    trust = ssl.create_default_context(cafile=str(root / ".devsec/ssl/ca/ca.crt"))
    port = "" if args.port == 443 else f":{args.port}"
    with httpx.Client(verify=trust, trust_env=False, timeout=10) as client:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                for environment in ("dev", "stage"):
                    url = f"https://photoagent-{environment}.home.arpa{port}"
                    assert client.get(f"{url}/health").json() == {"status": "ok"}
                    for path in ("/sessions", "/docs", "/openapi.json"):
                        assert client.get(f"{url}{path}").status_code == 404, path
                    context = browser.new_context()
                    page = context.new_page()
                    websockets: list[str] = []
                    page.on("websocket", lambda socket: websockets.append(socket.url))
                    page.goto(url)
                    expect(
                        page.get_by_placeholder("Что хочется узнать о фотографии?")
                    ).to_be_visible()
                    field = page.get_by_placeholder("Что хочется узнать о фотографии?")
                    field.fill("Объясни диафрагму")
                    field.press("Enter")
                    expect(page.get_by_text("Теоретические вопросы", exact=True)).to_be_visible()
                    assert any(address.startswith("wss://") for address in websockets)
                    context.close()
                    print(f"{environment}: TLS, health, ограничения маршрутов, WebSocket и чат OK")
            finally:
                browser.close()


if __name__ == "__main__":
    main()
