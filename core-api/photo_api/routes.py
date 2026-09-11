"""HTTP-маршруты с описанными контрактами."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Response, status

from shared.contracts import (
    ErrorResponse,
    HealthResponse,
    LeaseResponse,
    MessageRequest,
    MessageResponse,
    SessionResponse,
)

from .sessions import SessionStore

SessionId = Annotated[UUID, Path(description="Идентификатор текущей сессии")]
SESSION_ERRORS = {404: {"model": ErrorResponse, "description": "Сессия завершена или не найдена"}}


def session_routes(store: SessionStore) -> APIRouter:
    router = APIRouter(prefix="/sessions", tags=["Сессии"])

    @router.post(
        "",
        response_model=SessionResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Создание сессии",
        responses={503: {"model": ErrorResponse, "description": "Лимит активных сессий"}},
    )
    async def create_session() -> SessionResponse:
        return await store.create()

    @router.get(
        "/{session_id}",
        response_model=SessionResponse,
        status_code=status.HTTP_200_OK,
        summary="Получение контекста сессии",
        responses=SESSION_ERRORS,
    )
    async def get_session(session_id: SessionId) -> SessionResponse:
        return await store.get(session_id)

    @router.post(
        "/{session_id}/heartbeat",
        response_model=LeaseResponse,
        status_code=status.HTTP_200_OK,
        summary="Продление открытой сессии",
        responses=SESSION_ERRORS,
    )
    async def heartbeat(session_id: SessionId) -> LeaseResponse:
        return LeaseResponse(expires_at=await store.touch(session_id))

    @router.delete(
        "/{session_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        summary="Удаление сессии и её контекста",
        description="Повторное удаление также успешно: операция идемпотентна.",
    )
    async def delete_session(session_id: SessionId) -> Response:
        await store.delete(session_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/{session_id}/close",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        summary="Завершение сессии при закрытии вкладки",
        description="Вариант удаления для браузерного sendBeacon без тела запроса.",
    )
    async def close_session(session_id: SessionId) -> Response:
        await store.delete(session_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


def message_routes(store: SessionStore) -> APIRouter:
    router = APIRouter(tags=["Диалог"])

    @router.post(
        "/sessions/{session_id}/messages",
        response_model=MessageResponse,
        status_code=status.HTTP_200_OK,
        summary="Передача реплики и выделение тем",
        description="Вызывает только заглушки. Не обращается к ИИ, URL или поисковым сервисам.",
        responses={
            **SESSION_ERRORS,
            409: {"model": ErrorResponse, "description": "Конфликт отправки или лимит реплик"},
        },
    )
    async def send_message(session_id: SessionId, body: MessageRequest) -> MessageResponse:
        return await store.send(session_id, body)

    @router.get(
        "/health",
        response_model=HealthResponse,
        status_code=status.HTTP_200_OK,
        summary="Проверка доступности сервиса",
        tags=["Сервис"],
    )
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return router
