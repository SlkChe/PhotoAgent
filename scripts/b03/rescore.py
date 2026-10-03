"""Независимый пересчёт сохранённых выходов: python -m scripts.b03.rescore DIR."""

import argparse
import json
from pathlib import Path

from scripts.b03.run import CORPUS, digest
from scripts.b03.scoring import summarize, variability


def main() -> None:
    """Проверяет корпус и воспроизводит метрики без нового inference."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.directory / "manifest.json").read_text())
    if digest(CORPUS) != manifest["corpus_sha256"]:
        parser.error("Corpus SHA256 mismatch")
    corpus = json.loads(CORPUS.read_text())
    cases = [
        c for c in corpus["cases"] if manifest["split"] == "all" or c["split"] == manifest["split"]
    ]
    records = [
        json.loads(line) for line in (args.directory / "records.jsonl").read_text().splitlines()
    ]
    expected = {
        (c["case_id"], mode, repeat)
        for c in cases
        for mode in ("serial", "parallel3")
        for repeat in range(manifest["repeats"])
    }
    actual = [(r["case_id"], r["mode"], r["repeat"]) for r in records]
    if len(actual) != len(expected) or set(actual) != expected:
        parser.error("Missing or duplicate records")
    summary = json.loads((args.directory / "summary.json").read_text())
    if summarize(cases, records) != summary["metrics"]:
        parser.error("Metrics mismatch")
    if variability(cases, records) != summary["variability"]:
        parser.error("Variability mismatch")
    print(f"OK: {len(records)} records; corpus hash, coverage, metrics and variability match")


if __name__ == "__main__":
    main()
