"""Настройки жизненного цикла сессий из окружения."""

from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHOTO_API_", hide_input_in_errors=True)

    session_ttl_seconds: int = Field(default=180, ge=10, le=86400)
    cleanup_interval_seconds: float = Field(default=10, gt=0, le=60)
    max_sessions: int = Field(default=1000, ge=1, le=10000)
    max_turns: int = Field(default=100, ge=1, le=1000)

    llm_project_tokens_per_24h: int = Field(
        default=100000, gt=0, description="Общий лимит проекта за 24 часа, вход + выход"
    )
    llm_project_tokens_per_minute: int = Field(
        default=5000, gt=0, description="Общий минутный лимит проекта, вход + выход"
    )
    llm_project_tokens_per_request: int = Field(
        default=5000, gt=0, description="Верхний предел одного облачного вызова проекта"
    )
    llm_session_max_requests: int = Field(
        default=100, gt=0, description="Предел облачных вызовов за жизнь сессии"
    )
    llm_session_tokens_per_request: int = Field(
        default=1500, gt=0, description="Вход и зарезервированный выход одного вызова сессии"
    )
    llm_session_tokens_per_minute: int = Field(
        default=3000, gt=0, description="Минутный лимит отдельной сессии, вход + выход"
    )
    llm_estimated_chars_per_token: int = Field(
        default=3, gt=0, description="Символов на токен при предварительной оценке"
    )

    @model_validator(mode="after")
    def consistent_llm_limits(self) -> Self:
        if self.llm_session_tokens_per_request > self.llm_project_tokens_per_request:
            raise ValueError("PHOTO_API_LLM_SESSION_TOKENS_PER_REQUEST превышает предел проекта")
        if self.llm_session_tokens_per_minute > self.llm_project_tokens_per_minute:
            raise ValueError("PHOTO_API_LLM_SESSION_TOKENS_PER_MINUTE превышает предел проекта")
        if self.llm_session_tokens_per_request > self.llm_session_tokens_per_minute:
            raise ValueError("PHOTO_API_LLM_SESSION_TOKENS_PER_REQUEST превышает минутный предел")
        if self.llm_session_tokens_per_request > self.llm_project_tokens_per_24h:
            raise ValueError("PHOTO_API_LLM_SESSION_TOKENS_PER_REQUEST превышает предел за 24 часа")
        return self
