"""Экспорт проверяемого OpenAPI-кандидата B-01; не реализация HTTP-маршрутов."""

import json
from pathlib import Path

from pydantic import BaseModel

from shared.http_draft import operations as op
from shared.http_draft import session as view
from shared.mvp_contracts.execution import ApiError, ExecutionAccepted

DESTINATION = Path("docs/mvp-1/http-contract-openapi.json")
MODELS = (
    op.OperationRequest,
    op.SettingsUpdate,
    op.SettingsReceipt,
    op.MessageRequest,
    op.CancelClarification,
    op.BrowserContext,
    op.FeedbackUpdate,
    op.FeedbackReceipt,
    op.AnswerState,
    op.ExportPrepare,
    op.ExportReady,
    op.StatsReport,
    view.SessionSnapshot,
    view.ExecutionView,
    ApiError,
    ExecutionAccepted,
)


def reference(model: type[BaseModel]) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{model.__name__}"}


def parameter(name: str, where: str, description: str, **schema: object) -> dict[str, object]:
    return {
        "name": name,
        "in": where,
        "required": True,
        "description": description,
        "schema": schema or {"type": "string"},
    }


def response(model: type[BaseModel] | None, description: str) -> dict[str, object]:
    result: dict[str, object] = {
        "description": description,
        "headers": {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}},
    }
    if model is not None:
        result["content"] = {"application/json": {"schema": reference(model)}}
    return result


def operation(
    name: str,
    summary: str,
    security: str,
    outputs: dict[int, type[BaseModel] | None],
    body: type[BaseModel] | None = None,
    parameters: list[dict] | None = None,
    errors: dict[int, list[str]] | None = None,
) -> dict[str, object]:
    """Добавляет контракт успешных ответов и безопасные ошибки по каждому маршруту."""
    failures = {
        401: ["owner_unauthorized" if security == "owner" else "session_unavailable"],
        422: ["invalid_request"],
        500: ["internal_error"],
    }
    if security.startswith("browser"):
        failures[403] = ["invalid_origin", "invalid_csrf", "invalid_context"]
    if security == "browser-read":
        failures.pop(401)
    failures.update(errors or {})
    replies = {str(status): response(model, summary) for status, model in outputs.items()}
    for status, codes in failures.items():
        replies[str(status)] = response(ApiError, ", ".join(codes))
        replies[str(status)]["x-error-codes"] = codes
        if status in (429, 503):
            replies[str(status)]["headers"]["Retry-After"] = {
                "description": "Секунды до явной попытки, если известны; не команда retry",
                "schema": {"type": "integer", "minimum": 1},
            }
    policies = {
        "internal": [{"SessionBearer": []}],
        "owner": [{"OwnerBearer": []}],
        "browser": [{"BrowserContextCookie": [], "CsrfHeader": []}],
        "browser-read": [],
    }
    result: dict[str, object] = {
        "operationId": name,
        "summary": summary,
        "description": "ПРЕДЛОЖЕНИЕ B-01. Не реализовано. Семантика: http-contract-draft.md.",
        "tags": [security],
        "security": policies[security],
        "responses": replies,
        "parameters": parameters or [],
    }
    if body is not None:
        result["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": reference(body)}},
        }
    if security == "browser":
        result["parameters"].append(parameter("Origin", "header", "Точный допустимый HTTPS origin"))
    return result


def browser_paths() -> dict[str, object]:
    base = "/mvp1/browser/"
    paths = {
        base + "context": {
            "get": operation(
                "browserContext",
                "Получить CSRF-контекст",
                "browser-read",
                {200: op.BrowserContext},
                errors={403: ["invalid_origin"], 503: ["context_capacity"]},
            )
        }
    }
    for action, title in (
        ("session", "Создать сессию или повторить выдачу cookie"),
        ("opened", "Зарегистрировать явное открытие"),
        ("clear", "Отозвать доступ и очистить сессию"),
    ):
        paths[base + action] = {
            "post": operation(
                "browser" + action.title(),
                title,
                "browser",
                {204: None},
                op.OperationRequest,
                errors={
                    409: ["request_id_conflict", "creation_retired", "operation_capacity"],
                    503: ["session_capacity"],
                },
            )
        }
        if action in ("session", "clear"):
            paths[base + action]["post"]["responses"]["204"]["headers"]["Set-Cookie"] = {
                "description": "Secure; HttpOnly; SameSite=Lax; Path=/; без Domain",
                "schema": {"type": "string"},
            }
    for value in paths.values():
        endpoint = next(iter(value.values()))
        for name in ("__Host-photoagent", "__Host-photoagent-context"):
            cookie = parameter(name, "cookie", "Secure HttpOnly-cookie; не доступна JavaScript")
            cookie["required"] = False
            endpoint["parameters"].append(cookie)
    paths[base + "context"]["get"]["responses"]["200"]["headers"]["Set-Cookie"] = {
        "description": "HttpOnly CSRF-контекст, не новая сессия",
        "schema": {"type": "string"},
    }
    return paths


def session_paths() -> dict[str, object]:
    base = "/mvp1/internal/"
    execution_id = parameter(
        "execution_id", "path", "UUID не заменяет право доступа", type="string", format="uuid"
    )
    return {
        base + "session": {
            "get": operation(
                "sessionSnapshot",
                "Восстановить полный снимок",
                "internal",
                {200: view.SessionSnapshot},
            )
        },
        base + "session/settings": {
            "put": operation(
                "updateSettings",
                "Изменить настройки будущих отправок",
                "internal",
                {200: op.SettingsReceipt},
                op.SettingsUpdate,
                errors={409: ["session_busy", "settings_revision_conflict", "request_id_conflict"]},
            )
        },
        base + "messages": {
            "post": operation(
                "sendMessage",
                "Принять новую реплику или повторить доставку",
                "internal",
                {202: ExecutionAccepted, 200: view.ExecutionView},
                op.MessageRequest,
                errors={
                    409: [
                        "session_busy",
                        "settings_revision_conflict",
                        "request_id_conflict",
                        "clarification_conflict",
                        "session_history_limit",
                    ],
                    413: ["message_too_large"],
                    429: ["budget_exhausted", "rate_limited"],
                    503: ["queue_full"],
                },
            )
        },
        base + "executions/{execution_id}": {
            "get": operation(
                "executionStatus",
                "Прочитать состояние выполнения",
                "internal",
                {200: view.ExecutionView},
                parameters=[execution_id],
                errors={404: ["execution_not_found"]},
            )
        },
        base + "session/clarification/cancel": {
            "post": operation(
                "cancelClarification",
                "Снять ожидание уточнения",
                "internal",
                {204: None},
                op.CancelClarification,
                errors={409: ["request_id_conflict", "clarification_conflict", "session_busy"]},
            )
        },
    }


def feedback_paths() -> dict[str, object]:
    base = "/mvp1/internal/answers/{answer_id}/"
    identifier = parameter(
        "answer_id", "path", "Ответ только текущей сессии", type="string", format="uuid"
    )
    return {
        base + "shown": {
            "put": operation(
                "confirmShown",
                "Подтвердить первый показ ответа",
                "internal",
                {200: op.AnswerState},
                parameters=[identifier],
                errors={404: ["answer_not_found"], 409: ["answer_not_rateable"]},
            )
        },
        base + "feedback": {
            "put": operation(
                "updateFeedback",
                "Сохранить или заменить отзыв",
                "internal",
                {200: op.FeedbackReceipt},
                op.FeedbackUpdate,
                [identifier],
                errors={
                    404: ["answer_not_found"],
                    409: [
                        "answer_not_rateable",
                        "answer_not_shown",
                        "feedback_revision_conflict",
                        "request_id_conflict",
                    ],
                    413: ["comment_too_large"],
                },
            )
        },
    }


def export_paths() -> dict[str, object]:
    download = operation(
        "downloadExport",
        "Скачать файл согласованного снимка",
        "internal",
        {200: None},
        parameters=[
            parameter(
                "export_id",
                "path",
                "Снимок принадлежит текущей сессии",
                type="string",
                format="uuid",
            ),
            parameter(
                "kind", "path", "Один из двух файлов", type="string", enum=["dialogue", "sources"]
            ),
        ],
        errors={404: ["export_not_found", "export_empty"], 410: ["export_expired"]},
    )
    download["responses"]["200"]["content"] = {
        "text/markdown; charset=utf-8": {"schema": {"type": "string"}}
    }
    download["responses"]["200"]["headers"]["Content-Disposition"] = {
        "description": "attachment; безопасное фиксированное имя без текста пользователя",
        "schema": {"type": "string", "example": 'attachment; filename="dialogue.md"'},
    }
    return {
        "/mvp1/internal/exports": {
            "post": operation(
                "prepareExport",
                "Зафиксировать снимок для двух файлов",
                "internal",
                {201: op.ExportReady, 200: op.ExportReady},
                op.ExportPrepare,
                errors={
                    409: ["snapshot_revision_conflict", "request_id_conflict", "export_empty"],
                    410: ["export_expired"],
                    503: ["export_capacity"],
                },
            )
        },
        "/mvp1/internal/exports/{export_id}/{kind}": {"get": download},
    }


def attach_examples(schemas: dict) -> None:
    """Прикладывает валидируемые синтетические тела к Swagger-схемам."""
    path = DESTINATION.with_name("http-contract-examples.json")
    for item in json.loads(path.read_text())["examples"]:
        examples = schemas[item["model"]].setdefault("examples", [])
        if len(examples) < 3:
            examples.append(item["payload"])


def build_contract() -> dict[str, object]:
    """Собирает статический документ из предложенных моделей и утверждённого Answer."""
    schemas = {}
    for model in MODELS:
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(schema.pop("$defs", {}))
        schemas[model.__name__] = schema
    attach_examples(schemas)
    paths = browser_paths() | session_paths() | feedback_paths() | export_paths()
    paths["/mvp1/owner/statistics"] = {
        "get": operation(
            "downloadStatistics",
            "Выгрузить дневную статистику владельцу",
            "owner",
            {200: op.StatsReport},
            parameters=[
                parameter(
                    "from_date",
                    "query",
                    "Дата UTC включительно, максимум доступные 30 дней",
                    type="string",
                    format="date",
                ),
                parameter(
                    "to_date", "query", "Дата UTC включительно", type="string", format="date"
                ),
            ],
            errors={
                403: ["owner_forbidden"],
                422: ["invalid_request", "invalid_period"],
                503: ["statistics_unavailable"],
            },
        )
    }
    paths["/mvp1/owner/statistics"]["get"]["responses"]["200"]["headers"]["Content-Disposition"] = {
        "schema": {"type": "string", "example": 'attachment; filename="statistics.json"'}
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "B-01 HTTP — кандидат для согласования",
            "version": "mvp1-http-draft.1",
            "description": "Кандидат, не реализация. См. http-contract-draft.md.",
        },
        "servers": [{"url": "https://contract-not-deployed.invalid"}],
        "paths": paths,
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "SessionBearer": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Cookie сессии передаёт сервер UI; не доступен JS",
                },
                "OwnerBearer": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Отдельное право владельца; сессионный bearer не подходит",
                },
                "BrowserContextCookie": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "__Host-photoagent-context",
                },
                "CsrfHeader": {"type": "apiKey", "in": "header", "name": "X-PhotoAgent-CSRF"},
            },
        },
    }


if __name__ == "__main__":
    DESTINATION.write_text(json.dumps(build_contract(), ensure_ascii=False, indent=2) + "\n")
