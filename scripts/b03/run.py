"""Воспроизводимый прогон: python -m scripts.b03.run --help."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pydantic

from scripts.b03 import baseline
from scripts.b03.runtime import MemorySampler, model_analyze, start_server
from scripts.b03.schema import AnalysisInput
from scripts.b03.scoring import summarize, variability

CORPUS = Path("tests/fixtures/qa/query-corpus.json")


def digest(path: Path) -> str:
    """Фиксирует содержимое входа/реализации независимо от рабочего дерева."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def run_case(candidate: str, case: dict, mode: str, repeat: int) -> dict:
    """Изолирует запрос; ошибки сохраняет в общем знаменателе."""
    data = AnalysisInput(input=case["input"], context=case["context"])
    start = time.perf_counter()
    metadata = {}
    output = None
    error = None
    try:
        if candidate == "rules":
            projection = baseline.analyze(data)
        else:
            projection, metadata = model_analyze(data)
        output = projection.model_dump() if projection is not None else None
        if output is None:
            error = "invalid_or_truncated_output"
    except (ValueError, OSError, KeyError, IndexError, TypeError) as exc:
        error = type(exc).__name__
    return {
        "case_id": case["case_id"],
        "mode": mode,
        "repeat": repeat,
        "latency_ms": (time.perf_counter() - start) * 1000,
        "output": output,
        "error": error,
        "metadata": metadata,
    }


def manifest(candidate: str, repeats: int) -> dict:
    """Собирает несекретную provenance и заранее выбранные параметры."""
    hardware = subprocess.run(
        ["/usr/sbin/sysctl", "-n", "hw.model", "hw.memsize", "hw.ncpu"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    files = sorted(Path("scripts/b03").glob("*.py"))
    return {
        "candidate": candidate,
        "created_at": datetime.now(UTC).isoformat(),
        "pydantic": pydantic.__version__,
        "corpus_version": "0.3.0",
        "corpus_sha256": digest(CORPUS),
        "git_revision": revision,
        "source_sha256": {str(p): digest(p) for p in files},
        "platform": platform.platform(),
        "python": platform.python_version(),
        "hardware_model_memory_bytes_cpus": hardware,
        "repeats": repeats,
        "warmup_requests": 1,
        "timeout_seconds": 120,
        "seed": 42,
        "temperature": 0,
        "max_tokens": 768,
        "parallel_sessions": 3,
        "cache_prompt": False,
        "memory_method": "sum RSS runner+server sampled by ps every 100ms; GPU excluded",
        "percentile_method": "nearest rank; repeated cases are not independent samples",
        "queue": "at most 3 in-flight; latency measured inside worker incl HTTP/server wait; "
        "server queue delay not separately observable",
    }


def measure(
    candidate: str, cases: list[dict], repeats: int, output: Path, pids: list[int]
) -> tuple[list[dict], dict]:
    """Сначала serial, затем три независимых клиента; сбрасывает пик между режимами."""
    records = []
    resources = {}
    with (output / "records.jsonl").open("w") as stream:
        for mode, workers in [("serial", 1), ("parallel3", 3)]:
            started = time.perf_counter()
            with MemorySampler(pids) as memory, ThreadPoolExecutor(workers) as pool:
                for repeat in range(repeats):
                    rows = pool.map(lambda case: run_case(candidate, case, mode, repeat), cases)
                    for row in rows:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                        stream.flush()
                        records.append(row)
                    print(f"{candidate}: {mode}, repeat {repeat + 1}/{repeats}", flush=True)
            resources[mode] = {
                "wall_seconds": time.perf_counter() - started,
                "peak_rss_kib": memory.peak_kib,
                "rss_samples": memory.samples,
            }
    return records, resources


def main() -> None:
    """Не меняет корпус, не подключается к облаку, не перезаписывает результаты."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=["rules", "model"], required=True)
    parser.add_argument("--split", choices=["development", "evaluation", "all"], required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    corpus = json.loads(CORPUS.read_text())
    if corpus["corpus_version"] != "0.3.0":
        parser.error("Expected fixed corpus 0.3.0")
    cases = [c for c in corpus["cases"] if args.split == "all" or c["split"] == args.split]
    warmup = next(c for c in corpus["cases"] if c["split"] == "development")
    args.output.mkdir(parents=True, exist_ok=False)
    info = manifest(args.candidate, args.repeats)
    info["split"] = args.split
    process = None
    try:
        if args.candidate == "model":
            model = Path(".venv/b03-research/Qwen3-0.6B-Q8_0.gguf")
            info["model_sha256"] = digest(model)
            info["runtime_sha256"] = digest(Path(".venv/b03-research/llama-b11146/llama-server"))
            info["runtime_version"] = "0.5.0-dev b11146 7fe450e19"
            if (
                info["model_sha256"]
                != "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031"
            ):
                raise ValueError("Model hash mismatch")
            process, info["startup_ms"], info["server_command"] = start_server(args.output)
        info["warmup"] = run_case(args.candidate, warmup, "warmup", 0)
        (args.output / "manifest.json").write_text(json.dumps(info, ensure_ascii=False, indent=2))
        pids = [os.getpid()] + ([process.pid] if process else [])
        rows, resources = measure(args.candidate, cases, args.repeats, args.output, pids)
        result = {
            "metrics": summarize(cases, rows),
            "resources": resources,
            "variability": variability(cases, rows),
        }
        (args.output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        if process:
            process.terminate()
            process.wait(timeout=15)


if __name__ == "__main__":
    main()
