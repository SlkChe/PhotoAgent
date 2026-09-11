"""Изолированный HTTP-клиент без кеширования и автоматической повторной отправки."""

from uuid import UUID

import httpx

from shared.contracts import MessageRequest, MessageResponse, SessionResponse

from .settings import UiSettings


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ApiClient:
    def __init__(self, settings: UiSettings) -> None:
        self.base_url = str(settings.backend_url).rstrip("/")
        self.timeout = settings.request_timeout_seconds

    def _request(
        self,
        method: str,
        path: str,
        body: MessageRequest | None = None,
    ) -> httpx.Response:
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                response = client.request(
                    method,
                    self.base_url + path,
                    json=body.model_dump(mode="json") if body else None,
                )
                response.raise_for_status()
                return response
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            messages = {
                404: "Сессия завершена. Начните новый чат.",
                409: "Достигнут лимит диалога или возник конфликт отправки. Начните новый чат.",
                422: "Проверьте сообщение: от 1 до 4000 символов.",
                503: "Сервис занят. Попробуйте немного позже.",
            }
            raise ApiError(messages.get(code, "Сервис временно недоступен."), code) from None
        except httpx.RequestError:
            raise ApiError("Не удалось связаться с ассистентом. Проверьте подключение.") from None

    def create_session(self) -> SessionResponse:
        return SessionResponse.model_validate_json(self._request("POST", "/sessions").content)

    def delete_session(self, session_id: UUID) -> None:
        self._request("DELETE", f"/sessions/{session_id}")

    def heartbeat(self, session_id: UUID) -> None:
        self._request("POST", f"/sessions/{session_id}/heartbeat")

    def send(self, session_id: UUID, request: MessageRequest) -> MessageResponse:
        response = self._request("POST", f"/sessions/{session_id}/messages", request)
        return MessageResponse.model_validate_json(response.content)
