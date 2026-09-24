"""Локальный Swagger кандидата B-01; бизнес-маршруты не реализуются."""

import json
from pathlib import Path

from fastapi import FastAPI
from pydantic import JsonValue

app = FastAPI(
    title="B-01 — только просмотр кандидата",
    swagger_ui_parameters={"supportedSubmitMethods": []},
)


def contract() -> dict[str, JsonValue]:
    """Читает версионируемый документ; не объявляет рабочий сервис реализованным."""
    path = Path(__file__).resolve().parents[1] / "docs/mvp-1/http-contract-openapi.json"
    return json.loads(path.read_text())


app.openapi = contract
