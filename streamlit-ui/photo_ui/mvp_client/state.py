"""Состояние доставки: API остаётся источником истории и текущего выполнения."""

from dataclasses import dataclass, field
from uuid import uuid4

from shared.http_draft.operations import MessageRequest
from shared.http_draft.session import SessionSnapshot

from .transport import ClientError


@dataclass
class DeliveryState:
    snapshot: SessionSnapshot | None = field(default=None, repr=False)
    pending_json: str | None = field(default=None, repr=False)
    synchronized: bool = False
    draft: str = field(default="", repr=False)

    def restore(self, snapshot: SessionSnapshot) -> None:
        current = self.snapshot
        if current is not None and current.session_id != snapshot.session_id:
            self.synchronized = False
            raise ClientError("conflict", code="session_changed")
        if current is not None and snapshot.revision < current.revision:
            return
        if current is not None and snapshot.revision == current.revision and snapshot != current:
            self.synchronized = False
            raise ClientError("protocol", code="revision_mismatch")
        self.snapshot = snapshot.model_copy(deep=True)
        self.synchronized = True
        if self.pending_json is not None:
            pending = MessageRequest.model_validate_json(self.pending_json)
            if any(item.request_id == pending.request_id for item in snapshot.executions):
                self.pending_json = None
                if self.draft == pending.text:
                    self.draft = ""

    def prepare(self, text: str) -> MessageRequest:
        snapshot = self.snapshot
        if snapshot is None or not self.synchronized:
            raise ClientError("unavailable")
        if self.pending_json is not None or snapshot.session_status == "in_progress":
            raise ClientError("conflict", code="session_busy")
        if not text.strip() or len(text) > snapshot.capabilities.max_message_chars:
            raise ClientError("invalid")
        pending = snapshot.pending_clarification
        request = MessageRequest(
            request_id=uuid4(),
            text=text,
            settings_revision=snapshot.settings_revision,
            settings=snapshot.settings.model_copy(deep=True),
            clarification_id=pending.clarification_id if pending else None,
        )
        self.draft = text
        self.pending_json = request.model_dump_json()
        return request

    def retry(self) -> MessageRequest:
        if self.pending_json is None or not self.synchronized:
            raise ClientError("conflict", code="restore_before_retry")
        return MessageRequest.model_validate_json(self.pending_json)

    def failure(self, error: ClientError) -> None:
        self.synchronized = False
        if error.kind == "unavailable":
            self.snapshot = None
            self.pending_json = None
            self.draft = ""

    def accepted(self) -> None:
        self.synchronized = False
