"""Типизированный адаптер draft.1; браузерные cookie-операции выполняются отдельно."""

from uuid import UUID

from pydantic import SecretStr

from shared.http_draft.operations import MessageRequest, SettingsReceipt, SettingsUpdate
from shared.http_draft.session import ExecutionView, SessionSnapshot
from shared.mvp_contracts.execution import ExecutionAccepted

from .transport import ClientError, ClientSettings, Transport, decode


class DraftApiClient:
    def __init__(self, settings: ClientSettings) -> None:
        self.transport = Transport(settings)

    def snapshot(self, token: SecretStr) -> SessionSnapshot:
        response = self.transport.request("GET", "session", token)
        return decode(response, SessionSnapshot)

    def execution(self, token: SecretStr, execution_id: UUID) -> ExecutionView:
        response = self.transport.request("GET", f"executions/{execution_id}", token)
        result = decode(response, ExecutionView)
        if result.execution.execution_id != execution_id:
            raise ClientError("protocol", code="execution_mismatch")
        return result

    def send(
        self,
        token: SecretStr,
        request: MessageRequest,
        expected_session_id: UUID,
    ) -> ExecutionAccepted | ExecutionView:
        response = self.transport.request("POST", "messages", token, request)
        if response.status_code == 202:
            result = decode(response, ExecutionAccepted, 202)
            request_id = result.request_id
        else:
            result = decode(response, ExecutionView)
            request_id = result.execution.request_id
        if result.session_id != expected_session_id or request_id != request.request_id:
            raise ClientError("protocol", code="request_mismatch")
        return result

    def update_settings(self, token: SecretStr, request: SettingsUpdate) -> SettingsReceipt:
        response = self.transport.request("PUT", "session/settings", token, request)
        receipt = decode(response, SettingsReceipt)
        if receipt.request_id != request.request_id:
            raise ClientError("protocol", code="request_mismatch")
        return receipt
