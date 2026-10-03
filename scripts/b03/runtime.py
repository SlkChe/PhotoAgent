"""Только локальный HTTP, управляемый процесс и измерение RSS."""

import json
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from scripts.b03.examples import messages
from scripts.b03.schema import PROMPT, AnalysisInput, Projection

URL = "http://127.0.0.1:8087"


def request(path: str, payload: dict | None = None) -> dict:
    """Запрашивает фиксированный loopback без proxy и redirect."""

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        """Запрещает переадресацию вне локального endpoint."""

        def redirect_request(
            self, req: object, fp: object, code: int, msg: str, headers: object, newurl: str
        ) -> None:
            return None

    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(URL + path, body, {"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=120) as response:
        return json.load(response)


def model_analyze(data: AnalysisInput) -> tuple[Projection | None, dict]:
    """Отправляет чистый input/context с JSON Schema, без эталона."""
    response = request(
        "/v1/chat/completions",
        {
            "model": "b03-qwen",
            "messages": [
                {
                    "role": "system",
                    "content": PROMPT
                    + "\nJSON Schema:\n"
                    + json.dumps(Projection.model_json_schema(), ensure_ascii=False),
                },
                *messages(),
                {"role": "user", "content": data.model_dump_json()},
            ],
            "temperature": 0,
            "seed": 42,
            "max_tokens": 768,
            "cache_prompt": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "analysis",
                    "strict": True,
                    "schema": Projection.model_json_schema(),
                },
            },
        },
    )
    choice = response["choices"][0]
    raw = choice["message"]["content"]
    metadata = {
        "usage": response.get("usage"),
        "timings": response.get("timings"),
        "finish_reason": choice.get("finish_reason"),
        "raw": raw,
    }
    try:
        projection = Projection.model_validate_json(raw)
    except ValueError:
        return None, metadata
    if choice.get("finish_reason") != "stop":
        return None, metadata
    return projection, metadata


class MemorySampler:
    """Выборочный RSS процессов каждые 100 мс, без обещания измерить GPU."""

    def __init__(self, pids: list[int]) -> None:
        self.pids = pids
        self.peak_kib = 0
        self.samples = 0
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self) -> None:
        """Суммирует resident pages сервера и измерительного процесса."""
        while not self.done.is_set():
            result = subprocess.run(
                ["/bin/ps", "-o", "rss=", "-p", ",".join(map(str, self.pids))],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                self.peak_kib = max(self.peak_kib, sum(map(int, result.stdout.split())))
                self.samples += 1
            self.done.wait(0.1)

    def __enter__(self) -> "MemorySampler":
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.done.set()
        self.thread.join(timeout=2)


def start_server(output: Path) -> tuple[subprocess.Popen, float, list[str]]:
    """Запускает исследовательский процесс без секретов окружения."""
    try:
        request("/health")
    except OSError:
        pass
    else:
        raise RuntimeError("Порт 8087 занят; существующий сервер не используется")
    root = Path(".venv/b03-research")
    command = [
        str(root / "llama-b11146/llama-server"),
        "-m",
        str(root / "Qwen3-0.6B-Q8_0.gguf"),
        "--alias",
        "b03-qwen",
        "--host",
        "127.0.0.1",
        "--port",
        "8087",
        "--offline",
        "-c",
        "12288",
        "-np",
        "3",
        "-t",
        "4",
        "-tb",
        "4",
        "--reasoning",
        "off",
        "--no-cache-prompt",
        "--cache-ram",
        "0",
    ]
    start = time.perf_counter()
    with (output / "server.log").open("w") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=log,
            env={"PATH": "/usr/bin:/bin", "HOME": os.path.expanduser("~")},
        )
    try:
        for _ in range(600):
            if process.poll() is not None:
                raise RuntimeError("llama-server завершился; см. server.log")
            try:
                if request("/health").get("status") == "ok":
                    return process, (time.perf_counter() - start) * 1000, command
            except OSError:
                time.sleep(0.1)
        raise TimeoutError("Загрузка модели заняла более 60 секунд")
    except BaseException:
        process.terminate()
        process.wait(timeout=10)
        raise
