"""Отдельная фабрика FastAPI для F-01/B-02, без подключения к рабочему API."""

import asyncio
import hmac
import secrets
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from uuid import UUID

from fastapi import Cookie, Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.middleware.base import RequestResponseEndpoint

from .store import Context, ProbeError, ProbeStore, utc

COOKIE = "__Host-photoagent-f01"
CONTEXT_COOKIE = "__Host-photoagent-f01-context"


class Settings(BaseSettings):
    """Конфигурация отдельного экспериментального процесса."""

    model_config = SettingsConfigDict(env_prefix="PHOTO_PROBE_", hide_input_in_errors=True)
    origin: str = "https://photoagent-dev.home.arpa"
    max_contexts: int = Field(default=1000, ge=1, le=10000)


class Body(BaseModel):
    """Базовое тело без произвольных дополнительных полей."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Operation(Body):
    request_id: UUID = Field(description="ID явного действия", examples=[str(UUID(int=1))])


class Marker(Body):
    marker: str = Field(max_length=100, description="Синтетическая отметка", examples=["F-01"])


class BrowserContext(Body):
    session_id: UUID | None = Field(description="ID без права доступа", examples=[None])
    csrf_token: str = Field(description="CSRF текущего браузерного контекста", examples=["test"])


class Snapshot(Body):
    session_id: UUID = Field(description="ID для сравнения вкладок", examples=[str(UUID(int=1))])
    revision: int = Field(description="Версия отметки", examples=[1])
    last_activity_at: datetime = Field(description="Последнее явное действие UTC")
    expires_at: datetime = Field(description="Граница TTL UTC")
    marker: str = Field(description="Синтетическая отметка", examples=["F-01"])


class Error(Body):
    detail: str = Field(description="Стабильный код ошибки", examples=["session_unavailable"])


def set_cookie(response: Response, name: str, value: str) -> None:
    """Выдаёт сессионную host-only HttpOnly-cookie без постоянного срока."""
    response.set_cookie(name, value, secure=True, httponly=True, samesite="lax", path="/")


def create_app(settings: Settings | None = None, clock: Callable[[], float] = time.time) -> FastAPI:
    """Создаёт один изолированный процесс; часы внедряются только из Python-тестов."""
    configuration = settings or Settings()
    store = ProbeStore(clock, configuration.max_contexts)
    errors = {code: {"model": Error} for code in (401, 403, 409, 422, 503)}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(cleanup(store))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            store.contexts.clear()

    app = FastAPI(
        title="B-02 session experiment", version="0.1", responses=errors, lifespan=lifespan
    )

    @app.middleware("http")
    async def no_store(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ProbeError)
    async def failure(request: Request, exc: ProbeError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.code})

    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "invalid_request"})

    register_browser(app, store, configuration.origin)
    register_mutations(app, store, configuration.origin)
    register_clear(app, store, configuration.origin)
    return app


def guard(request: Request, store: ProbeStore, origin: str) -> tuple[str, Context]:
    """Проверяет точный Origin, cookie-контекст и CSRF перед любым изменением."""
    if request.headers.get("origin") != origin:
        raise ProbeError(403, "invalid_origin")
    seed, context = store.context(request.cookies.get(CONTEXT_COOKIE))
    provided = request.headers.get("x-f01-csrf", "")
    if not hmac.compare_digest(provided.encode(), store.csrf(seed, context).encode()):
        raise ProbeError(403, "invalid_csrf")
    return seed, context


def register_browser(app: FastAPI, store: ProbeStore, origin: str) -> None:
    """Регистрирует чтение контекста и внутренний снимок без продления TTL."""

    @app.get(
        "/f01/browser/context",
        response_model=BrowserContext,
        status_code=200,
        summary="Получить CSRF-контекст",
        tags=["browser"],
        dependencies=[Depends(browser_parameters)],
    )
    async def context(request: Request, response: Response) -> BrowserContext:
        if request.headers.get("sec-fetch-site") == "cross-site" or (
            request.headers.get("origin") not in (None, origin)
        ):
            raise ProbeError(403, "invalid_origin")
        seed, browser = store.context(request.cookies.get(CONTEXT_COOKIE), create=True)
        set_cookie(response, CONTEXT_COOKIE, seed)
        session_id = None
        try:
            session_id = store.authorized(request.cookies.get(COOKIE), browser).id
        except ProbeError:
            pass
        return BrowserContext(session_id=session_id, csrf_token=store.csrf(seed, browser))

    @app.get(
        "/f01/internal/snapshot",
        response_model=Snapshot,
        status_code=200,
        summary="Прочитать снимок без активности",
        tags=["internal"],
    )
    async def snapshot(
        authorization: str | None = Header(
            default=None, description="Bearer из HttpOnly-cookie UI"
        ),
    ) -> Snapshot:
        header = authorization or ""
        token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else None
        session = store.authorized(token)
        return Snapshot(
            session_id=session.id,
            revision=session.revision,
            last_activity_at=utc(session.activity),
            expires_at=utc(session.activity + 43200),
            marker=session.marker,
        )


def register_mutations(app: FastAPI, store: ProbeStore, origin: str) -> None:
    """Регистрирует явные браузерные действия с общей CSRF-проверкой."""

    @app.post(
        "/f01/browser/create",
        status_code=204,
        response_class=Response,
        summary="Создать или восстановить выдачу cookie",
        tags=["browser"],
        dependencies=[Depends(browser_parameters)],
    )
    async def create(request: Request, body: Operation) -> Response:
        seed, context = guard(request, store, origin)
        token = store.create(seed, context, body.request_id)
        response = Response(status_code=204)
        set_cookie(response, COOKIE, token)
        return response

    @app.post(
        "/f01/browser/opened",
        status_code=204,
        response_class=Response,
        summary="Учесть явное открытие документа",
        tags=["browser"],
        dependencies=[Depends(browser_parameters)],
    )
    async def opened(request: Request, body: Operation) -> Response:
        _, context = guard(request, store, origin)
        store.opened(store.authorized(request.cookies.get(COOKIE), context), body.request_id)
        return Response(status_code=204)

    @app.post(
        "/f01/browser/marker",
        status_code=204,
        response_class=Response,
        summary="Записать синтетическую отметку",
        tags=["browser"],
        dependencies=[Depends(browser_parameters)],
    )
    async def marker(request: Request, body: Marker) -> Response:
        _, context = guard(request, store, origin)
        session = store.authorized(request.cookies.get(COOKIE), context)
        session.marker = body.marker
        session.revision += 1
        session.activity = store.clock()
        return Response(status_code=204)


def register_clear(app: FastAPI, store: ProbeStore, origin: str) -> None:
    """Отзыв доступа и ротация CSRF защищают новый диалог от старой очистки."""

    @app.post(
        "/f01/browser/clear",
        status_code=204,
        response_class=Response,
        summary="Отозвать доступ и очистить данные",
        tags=["browser"],
        dependencies=[Depends(browser_parameters)],
    )
    async def clear(request: Request, body: Body) -> Response:
        _, context = guard(request, store, origin)
        if context.session:
            store.authorized(request.cookies.get(COOKIE), context)
        context.session = None
        context.epoch = secrets.token_hex(16)
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response


async def cleanup(store: ProbeStore) -> None:
    """Очищает просроченные данные даже при отсутствии новых запросов."""
    while True:
        await asyncio.sleep(60)
        store.sweep()


def browser_parameters(
    origin: str | None = Header(default=None, description="Точный Origin; обязателен для POST"),
    csrf: str | None = Header(
        default=None, alias="X-F01-CSRF", description="CSRF из context для POST"
    ),
    context: str | None = Cookie(
        default=None, alias=CONTEXT_COOKIE, description="HttpOnly-контекст"
    ),
    token: str | None = Cookie(default=None, alias=COOKIE, description="HttpOnly-доступ к сессии"),
) -> None:
    """Описывает параметры; их обязательность и ошибки 403/401 проверяет guard."""
