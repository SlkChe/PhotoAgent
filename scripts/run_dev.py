"""Запуск одного Dev-сервиса с ограниченным набором переменных окружения."""

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("api", "ui"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    python = root / ".venv/runtime-env/bin/python"
    if not python.is_file():
        parser.error("Сначала создайте .venv/runtime-env по README.md")
    common = {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT"}
    prefix = "PHOTO_API_" if args.service == "api" else "PHOTO_UI_"
    environment = {
        key: value for key, value in os.environ.items() if key in common or key.startswith(prefix)
    }
    if args.service == "api":
        environment["PYTHONPATH"] = ".:core-api"
        command = [
            "-m",
            "uvicorn",
            "photo_api.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--no-access-log",
        ]
    else:
        environment["PYTHONPATH"] = ".:streamlit-ui"
        environment["PHOTO_UI_BACKEND_URL"] = "http://127.0.0.1:8000"
        environment["PHOTO_UI_PUBLIC_BACKEND_URL"] = "https://photoagent-dev.home.arpa"
        command = [
            "-m",
            "streamlit",
            "run",
            "streamlit-ui/app.py",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            "8501",
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ]
    os.chdir(root)
    os.execve(python, [str(python), *command], environment)


if __name__ == "__main__":
    main()
