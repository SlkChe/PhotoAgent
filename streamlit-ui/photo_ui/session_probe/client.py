"""Чтение состояния экспериментального API без продления сессии."""

from uuid import UUID

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProbeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHOTO_F01_")

    backend_url: HttpUrl
    cookie_name: str = Field(default="__Host-photoagent-f01", pattern=r"^[A-Za-z0-9_-]+$")
    request_timeout_seconds: float = Field(default=5, gt=0, le=30)
    poll_seconds: int = Field(default=3, ge=1, le=30)


class ProbeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID = Field(description="Идентификатор для сравнения вкладок, не токен доступа")
    revision: int = Field(ge=0, description="Версия состояния стенда")
    last_activity_at: AwareDatetime = Field(description="Последняя явная активность, UTC")
    expires_at: AwareDatetime = Field(description="Граница серверного TTL, UTC")
    marker: str = Field(
        max_length=100, description="Синтетическая отметка для проверки восстановления"
    )

    @model_validator(mode="after")
    def check_dates(self) -> "ProbeSnapshot":
        if self.expires_at <= self.last_activity_at:
            raise ValueError("Некорректная граница TTL")
        return self

    def diagnostic(self) -> dict[str, str | int]:
        return {
            "session_id": str(self.session_id),
            "revision": self.revision,
            "last_activity_at": self.last_activity_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "marker": self.marker,
        }


class ProbeError(Exception):
    def __init__(self, unavailable: bool = False) -> None:
        super().__init__(
            "Сессия недоступна" if unavailable else "Не удалось прочитать состояние API"
        )
        self.unavailable = unavailable


class ProbeClient:
    def __init__(self, settings: ProbeSettings) -> None:
        self.settings = settings

    def snapshot(self, token: str) -> ProbeSnapshot:
        try:
            with httpx.Client(
                timeout=self.settings.request_timeout_seconds,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                response = client.get(
                    f"{str(self.settings.backend_url).rstrip('/')}/f01/internal/snapshot",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if response.status_code in (401, 410):
                raise ProbeError(unavailable=True)
            if response.status_code != 200:
                raise ProbeError()
            return ProbeSnapshot.model_validate_json(response.content)
        except httpx.HTTPError, ValueError:
            raise ProbeError() from None
