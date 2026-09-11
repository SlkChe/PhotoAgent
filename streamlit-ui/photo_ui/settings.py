"""Настройки соединения с бэкендом."""

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class UiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHOTO_UI_")

    backend_url: HttpUrl
    public_backend_url: HttpUrl
    request_timeout_seconds: float = Field(default=10, gt=0, le=60)
    heartbeat_seconds: int = Field(default=20, ge=5, le=60)
