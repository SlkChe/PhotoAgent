"""Прозрачный словарный baseline; настроен только на development."""

import re

from scripts.b03.schema import AnalysisInput, Entity, Projection

TOPICS = {
    "technology": (
        r"объектив|фокусн|выдержк|диафрагм|экспозици|сенсор|матриц|"
        r"записи цвета|цветн|камер|техник"
    ),
    "art": r"минимализм|абстракт|художествен|эстетик|композиц|искусств|пикториализм",
    "actors": r"агентств|фотограф[а-я]*\s+[А-Я]|биограф|организац",
    "genres": r"портрет|репортаж|спортивн|пейзаж|натюрморт|жанр|документальн|уличн",
    "works": r"сери[яюи]|снимок|снимк|альбом|книг|произведени",
}
INTENTS = [
    ("fact_check", r"верно ли|правда ли|проверь|утверждени"),
    ("compare", r"сопостав|сравни|отлич|разниц"),
    ("source_selection", r"подбер.*материал|источник|литератур|почитать"),
    ("timeline", r"хронологи|по годам|последовательност.*этап"),
    ("artistic_significance", r"художествен.*значени|влияни.*искусств"),
    ("historical_overview", r"историческ.*обзор|истори.*развити|как развивал"),
    ("explain", r"означает|поясни|объясни|почему|как работает|что такое"),
]
OUTSIDE = (
    r"купить|аренд|магазин|цен[аыу]|студи[юи].*снять|"
    r"выставк.*сегодня|оцени.*фото|погод|рецепт"
)


def choose_intent(text: str) -> str:
    """Проверяет intent в фиксированном порядке приоритетов."""
    if "агентств" in text:
        return "reference"
    return next((name for name, pattern in INTENTS if re.search(pattern, text)), "reference")


def context_entities(data: AnalysisInput, text: str) -> list[dict[str, str | None]]:
    """Разрешает ссылки только на явно переданные сущности."""
    entities = data.context.get("entities", [])
    if not isinstance(entities, list) or re.search(r"сменим тему|другая тема|теперь о", text):
        return []
    result = []
    for item in entities:
        if isinstance(item, dict) and isinstance(item.get("label"), str):
            result.append(
                {
                    "kind": str(item.get("kind", "unknown")),
                    "label": item["label"],
                    "context_id": str(item.get("id")),
                }
            )
    return result


def analyze(data: AnalysisInput) -> Projection:
    """Строит независимую проекцию без доступа к разметке QA."""
    text = data.input.lower()
    topics = [name for name, pattern in TOPICS.items() if re.search(pattern, text)]
    entities = context_entities(data, text)
    if not topics and entities:
        topics = ["works" if any(e["kind"] == "work" for e in entities) else "actors"]
    outside = bool(re.search(OUTSIDE, text))
    scope = "mixed" if outside and topics else "out_of_scope" if outside else "in_scope"
    act = "ask"
    if re.search(r"^(да|ага|верно|хорошо)[.!\s]*$", text):
        act = "confirm"
    elif re.search(r"отмен|не надо|стоп", text):
        act = "cancel"
    elif data.context.get("pending_clarification"):
        act = "clarification_reply"
    elif re.search(r"перефраз|иначе|проще|короче", text):
        act = "rephrase"
    elif re.search(r"сменим тему|другая тема|теперь о", text):
        act = "change_subject"
    clarification = not topics and not outside and act == "ask"
    clarification = clarification and data.context.get("clarification_rounds_used", 0) == 0
    service = act in {"cancel", "confirm"} or scope == "out_of_scope"
    search = "none" if service or clarification else "required_for_new_facts"
    if act == "rephrase" and data.context.get("evidence_available"):
        search = "reuse_evidence"
    return Projection.model_validate(
        {
            "topics": topics,
            "intent": None if service else choose_intent(text),
            "dialogue_act": act,
            "scope_status": scope,
            "needs_clarification": clarification,
            "response_mode": None
            if service
            else ("thematic_overview" if "обзор" in text else "focused"),
            "role": data.context.get("current_role"),
            "entities": [Entity.model_validate(e).model_dump() for e in entities],
            "excluded_parts": [data.input] if outside else [],
            "subquestion_intents": [],
            "search": search,
            "cloud_generation": "none" if service or clarification else "allowed_after_evidence",
        }
    )
