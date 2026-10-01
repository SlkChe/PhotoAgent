"""Транспорт внутреннего API: таймаут, bearer и отсутствие скрытых повторов."""

from typing import Literal

import httpx
from pydantic import BaseModel, Field, HttpUrl, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

type FailureKind = Literal[
    "network", "unavailable", "forbidden", "conflict", "invalid", "limited", "server", "protocol"
]


class ClientSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHOTO_MVP_UI_")

    backend_url: HttpUrl
    timeout_seconds: float = Field(default=10, gt=0, le=60)
    allow_draft_contract: bool = False


class ClientError(Exception):
    def __init__(
        self,
        kind: FailureKind,
        status: int | None = None,
        code: str = "request_failed",
        retry_after: int | None = None,
    ) -> None:
        super().__init__(kind)
        self.kind = kind
        self.status = status
        self.code = code
        self.retry_after = retry_after


_CODES = frozenset(
    {
        "session_unavailable",
        "session_changed",
        "session_busy",
        "invalid_csrf",
        "invalid_origin",
        "invalid_context",
        "request_id_conflict",
        "settings_revision_conflict",
        "feedback_revision_conflict",
        "clarification_conflict",
        "answer_not_shown",
        "answer_not_rateable",
        "invalid_request",
        "budget_exhausted",
        "queue_full",
    }
)


def response_error(response: httpx.Response) -> ClientError:
    status = response.status_code
    kinds: dict[int, FailureKind] = {
        401: "unavailable",
        403: "forbidden",
        409: "conflict",
        413: "invalid",
        422: "invalid",
        429: "limited",
    }
    kind = kinds.get(status, "server" if status >= 500 else "protocol")
    code = "request_failed"
    try:
        payload = response.json()
        value = payload.get("code") if isinstance(payload, dict) else None
        if isinstance(value, str) and value in _CODES:
            code = value
    except ValueError:
        pass
    delay = response.headers.get("Retry-After", "")
    retry_after = int(delay) if delay.isascii() and delay.isdigit() and len(delay) <= 8 else None
    return ClientError(kind, status, code, retry_after)


class Transport:
    def __init__(self, settings: ClientSettings) -> None:
        self.settings = settings

    def request(
        self,
        method: str,
        path: str,
        token: SecretStr,
        body: BaseModel | None = None,
    ) -> httpx.Response:
        if not self.settings.allow_draft_contract:
            raise ClientError("protocol", code="draft_contract_disabled")
        try:
            with httpx.Client(
                timeout=self.settings.timeout_seconds,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                return client.request(
                    method,
                    f"{str(self.settings.backend_url).rstrip('/')}/mvp1/internal/{path}",
                    headers={"Authorization": f"Bearer {token.get_secret_value()}"},
                    json=body.model_dump(mode="json") if body is not None else None,
                )
        except httpx.HTTPError, ValueError:
            raise ClientError("network") from None


def decode[T: BaseModel](response: httpx.Response, model: type[T], expected: int = 200) -> T:
    if response.status_code != expected:
        raise response_error(response)
    try:
        return model.model_validate_json(response.content)
    except ValidationError:
        raise ClientError("protocol", response.status_code, "incompatible_response") from None
