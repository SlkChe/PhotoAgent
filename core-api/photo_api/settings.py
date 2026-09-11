"""Настройки жизненного цикла сессий из окружения."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHOTO_API_")

    session_ttl_seconds: int = Field(default=180, ge=10, le=86400)
    cleanup_interval_seconds: float = Field(default=10, gt=0, le=60)
    max_sessions: int = Field(default=1000, ge=1, le=10000)
    max_turns: int = Field(default=100, ge=1, le=1000)
