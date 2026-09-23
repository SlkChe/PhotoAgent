"""Детерминированные ответы SDK LiteLLM, без маршрутизации к провайдерам."""

import asyncio
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Response
from litellm.main import mock_completion
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Scenario = Literal[
    "echo",
    "fixture",
    "rate-limit",
    "server-error",
    "delay",
    "malformed-json",
    "length",
    "missing-usage",
    "invalid-usage",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHOTO_MOCK_")
    delay_seconds: float = Field(default=2, gt=0, le=30)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=16000, description="Только синтетический текст")


class CompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Scenario = Field(description="Название тестового сценария", examples=["echo"])
    messages: list[Message] = Field(min_length=1, max_length=20)
    stream: Literal[False] = False
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = None


class State(BaseModel):
    status: Literal["ok"] = "ok"
    calls: int = Field(description="Число принятых completion-запросов с момента сброса")


settings = Settings()
app = FastAPI(title="PhotoAgent isolated LiteLLM mock", version="1")
calls = 0
fixture = Path("/fixtures/llm-draft.json").read_text(encoding="utf-8").strip()
json.loads(fixture)


@app.get("/health", response_model=State, status_code=200, summary="Готовность mock")
@app.get("/__test/state", response_model=State, status_code=200, summary="Счётчик вызовов")
async def state() -> State:
    return State(calls=calls)


@app.post("/__test/reset", response_model=State, status_code=200, summary="Сброс счётчика")
async def reset() -> State:
    global calls
    calls = 0
    return State(calls=calls)


def completion_response(body: CompletionRequest) -> Response:
    content = next((m.content for m in reversed(body.messages) if m.role == "user"), "")
    if body.model != "echo":
        content = fixture
    # Вызывается непосредственно mock SDK; сетевой completion/router не используется.
    result = mock_completion(
        model="openai/test-model",
        messages=[message.model_dump() for message in body.messages],
        mock_response={
            "id": "chatcmpl-photoagent-test",
            "object": "chat.completion",
            "created": 0,
            "model": body.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "length" if body.model == "length" else "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        },
    ).model_dump(exclude_none=True)
    if body.model == "missing-usage":
        result.pop("usage", None)
    elif body.model == "invalid-usage":
        result["usage"] = {"prompt_tokens": -1, "completion_tokens": "invalid"}
    return Response(json.dumps(result), media_type="application/json")


@app.post(
    "/v1/chat/completions",
    response_class=Response,
    status_code=200,
    summary="Синтетический OpenAI-совместимый ответ",
    responses={
        200: {"description": "Completion JSON или намеренно повреждённый JSON сценария"},
        429: {"description": "Тестовый rate limit с Retry-After: 1"},
        503: {"description": "Тестовый отказ"},
    },
)
async def completion(body: CompletionRequest) -> Response:
    global calls
    calls += 1
    if body.model in ("rate-limit", "server-error"):
        code = 429 if body.model == "rate-limit" else 503
        headers = {"Retry-After": "1"} if code == 429 else {}
        return Response(
            '{"error":{"message":"Synthetic failure","type":"test_error"}}',
            status_code=code,
            headers=headers,
            media_type="application/json",
        )
    if body.model == "delay":
        await asyncio.sleep(settings.delay_seconds)
    if body.model == "malformed-json":
        return Response('{"choices":', media_type="application/json")
    return completion_response(body)
