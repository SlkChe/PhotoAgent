"""Два примера только из development: T02-001 и T02-004, без evaluation."""

import json

EXAMPLES = [
    (
        "Что означает фокусное расстояние объектива?",
        ["technology"],
        "explain",
        [{"kind": "technology", "label": "фокусное расстояние", "context_id": None}],
    ),
    (
        "Сопоставьте постановочный и репортажный портрет по способу работы фотографа.",
        ["genres"],
        "compare",
        [],
    ),
]


def messages() -> list[dict[str, str]]:
    """Демонстрирует формат; роль примеров выбрана по политике, не QA-метке."""
    result = []
    for text, topics, intent, entities in EXAMPLES:
        data = {
            "input": text,
            "context": {
                "locale": "ru",
                "current_role": None,
                "messages": [],
                "entities": [],
                "clarification_rounds_used": 0,
                "pending_clarification": None,
                "evidence_available": False,
            },
        }
        answer = {
            "topics": topics,
            "intent": intent,
            "dialogue_act": "ask",
            "scope_status": "in_scope",
            "needs_clarification": False,
            "response_mode": "focused",
            "role": "Технический эксперт",
            "entities": entities,
            "excluded_parts": [],
            "subquestion_intents": [],
            "search": "required_for_new_facts",
            "cloud_generation": "allowed_after_evidence",
        }
        result.extend(
            [
                {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
                {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
            ]
        )
    return result
