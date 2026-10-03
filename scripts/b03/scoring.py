"""Пересчёт метрик без изменения знаменателей при ошибках."""

import math
from collections import defaultdict

from pydantic import JsonValue


def score_case(case: dict, output: dict | None) -> dict[str, bool]:
    """Сравнивает только поля с принятым эталоном."""
    expected = case["expected"]
    result = {}
    for field in case["annotation"]["scored_fields"]:
        target = expected[field]
        if field == "role":
            if target["status"] == "pending_A13":
                continue
            target = target["value"]
        actual = output.get(field) if output is not None else None
        if output is None or field not in output:
            result[field] = False
        elif field == "topics":
            result[field] = set(actual) == set(target)
        elif field == "needs_clarification" and "clarification_options" in expected:
            result[field] = actual in expected["clarification_options"]
        else:
            result[field] = actual == target
    return result


def summarize(cases: list[dict], records: list[dict]) -> dict[str, JsonValue]:
    """Отдельно считает split/нагрузку, сырые задержки остаются в records."""
    indexed = {case["case_id"]: case for case in cases}
    groups = defaultdict(list)
    for record in records:
        groups[(record["mode"], indexed[record["case_id"]]["split"])].append(record)
    summary = {}
    for (mode, split), rows in groups.items():
        fields = defaultdict(lambda: {"correct": 0, "total": 0, "errors": []})
        for row in rows:
            for field, correct in score_case(indexed[row["case_id"]], row["output"]).items():
                fields[field]["total"] += 1
                fields[field]["correct"] += int(correct)
                if not correct:
                    fields[field]["errors"].append(row["case_id"])
        timings = sorted(row["latency_ms"] for row in rows)
        summary[f"{mode}/{split}"] = {
            "n": len(rows),
            "invalid": sum(row["output"] is None for row in rows),
            "p50_ms": timings[math.ceil(len(timings) * 0.5) - 1],
            "p95_ms": timings[math.ceil(len(timings) * 0.95) - 1],
            "fields": dict(fields),
        }
    return summary


def variability(cases: list[dict], records: list[dict]) -> dict[str, JsonValue]:
    """Отделяет устойчивость повторов от точности и допустимого уточнения."""
    import json

    result = {}
    for case in cases:
        rows = [r for r in records if r["case_id"] == case["case_id"]]
        outputs = {json.dumps(r["output"], sort_keys=True, ensure_ascii=False) for r in rows}
        item = {"distinct_outputs": len(outputs), "n": len(rows)}
        if "clarification_options" in case["expected"]:
            item["allowed_clarification"] = case["expected"]["clarification_options"]
            item["observed_clarification"] = [
                r["output"]["needs_clarification"] if r["output"] else None for r in rows
            ]
        result[case["case_id"]] = item
    return result
