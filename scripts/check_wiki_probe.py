"""B-07: ограниченная публичная проба MediaWiki search + plaintext extract."""

import json

import httpx


def main() -> None:
    """Не сохраняет полный текст; выдаёт атрибуцию, размер и статус операций."""
    params: dict[str, str | int] = {
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "generator": "search",
        "gsrsearch": "photography depth of field",
        "gsrlimit": 1,
        "prop": "extracts|info",
        "inprop": "url",
        "explaintext": 1,
        "exintro": 1,
        "exchars": 1000,
    }
    try:
        with httpx.Client(
            timeout=20,
            trust_env=False,
            follow_redirects=False,
            headers={"User-Agent": "PhotoAgent-MVP1-Research/0.1"},
        ) as client:
            response = client.get("https://en.wikipedia.org/w/api.php", params=params)
        response.raise_for_status()
        pages = response.json()["query"]["pages"]
        for page in pages:
            print(
                json.dumps(
                    {
                        "title": page["title"],
                        "url": page["fullurl"],
                        "extract_chars": len(page.get("extract", "")),
                        "text_kind": "excerpt",
                        "language": "en",
                    },
                    ensure_ascii=False,
                )
            )
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "not_verified", "reason": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
