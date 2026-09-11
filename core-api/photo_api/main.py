"""Создание FastAPI-приложения и очистка завершённых сессий."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from shared.contracts import ErrorResponse

from .routes import message_routes, session_routes
from .sessions import SessionError, SessionStore
from .settings import ApiSettings


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    configuration = settings or ApiSettings()
    store = SessionStore(configuration)

    async def cleanup() -> None:
        while True:
            await asyncio.sleep(configuration.cleanup_interval_seconds)
            await store.sweep()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(cleanup())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await store.clear()

    app = FastAPI(
        title="PhotoAgent API",
        version="0.1.0",
        description="Прототип: сессии, контекст и тематические заглушки.",
        lifespan=lifespan,
    )

    @app.exception_handler(SessionError)
    async def session_error(request: Request, exc: SessionError) -> JSONResponse:
        body = ErrorResponse(detail=exc.detail)
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    app.include_router(session_routes(store))
    app.include_router(message_routes(store))
    return app
