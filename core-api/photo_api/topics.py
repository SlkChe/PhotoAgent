"""Заменяемый каркас декомпозиции без обращений к ИИ и внешним сервисам."""

import re
from collections.abc import Callable

from shared.contracts import TOPIC_LABELS, Topic


def confirmation_stub() -> str:
    return TOPIC_LABELS[Topic.CONFIRMATION]


def search_stub() -> str:
    return TOPIC_LABELS[Topic.SEARCH]


def theory_stub() -> str:
    return TOPIC_LABELS[Topic.THEORY]


def frame_stub() -> str:
    return TOPIC_LABELS[Topic.FRAME]


HANDLERS: dict[Topic, Callable[[], str]] = {
    Topic.CONFIRMATION: confirmation_stub,
    Topic.SEARCH: search_stub,
    Topic.THEORY: theory_stub,
    Topic.FRAME: frame_stub,
}

PATTERNS: dict[Topic, str] = {
    Topic.CONFIRMATION: r"^(да|ага|ок|окей|хорошо|согласен|согласна|продолжай|подтверждаю)\b",
    Topic.SEARCH: (
        r"\b(найди|найти|подбери|подобрать|купить|куплю|аренд\w*|прокат\w*|"
        r"студи\w*|визажист\w*|услуг\w*|оборудован\w*|посоветуй\s+объектив)\b"
    ),
    Topic.THEORY: (
        r"\b(объясни|расскажи|теори\w*|что\s+такое|как\s+работает|"
        r"композици\w*|диафрагм\w*|выдержк\w*|экспозици\w*|глубин\w*\s+резкости)\b"
    ),
    Topic.FRAME: (
        r"\b(этот\s+кадр|этом\s+кадре|эту\s+фотографию|мо[йею]\s+"
        r"(кадр|фото|снимок)|на\s+(фото|снимке|кадре)|оцени|разбери|проанализируй)\b"
        r"|https?://"
    ),
}


def decompose(text: str, previous_topics: list[Topic]) -> list[Topic]:
    """На старте используем прозрачные эвристики; позднее заменим классификатор."""
    normalized = text.casefold().replace("ё", "е").strip()
    topics = [topic for topic, pattern in PATTERNS.items() if re.search(pattern, normalized)]
    if not topics and re.match(r"^(а\s+)?(почему|как|подробнее|зачем)\b", normalized):
        return [topic for topic in previous_topics if topic != Topic.CONFIRMATION]
    return topics


def dispatch(topics: list[Topic]) -> str:
    return "\n".join(HANDLERS[topic]() for topic in topics) or "Тема не определена"
