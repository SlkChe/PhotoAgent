"""Данные представления, независимые от незавершённого HTTP-контракта."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MessageView(BaseModel):
    message_id: str
    kind: Literal["user", "assistant"]
    text: str
    author: str = ""


class SourceView(BaseModel):
    card_id: str
    title: str
    url: str
    context_comment: str
    first_message_id: str


class LayoutView(BaseModel):
    session_key: str = "empty"
    current_role: str = ""
    status: str = ""
    input_disabled: bool = False
    settings_disabled: bool = False
    draft_revision: int = 0
    submission_revision: int = 0
    detail: Literal["brief", "detailed"] = "brief"
    level: Literal["beginner", "advanced"] = "beginner"
    messages: list[MessageView] = Field(default_factory=list)
    sources: list[SourceView] = Field(default_factory=list)


class LayoutEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: Literal["send", "settings"]
    text: str = ""
    detail: Literal["brief", "detailed"] = "brief"
    level: Literal["beginner", "advanced"] = "beginner"
