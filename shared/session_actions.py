"""Принятое тело браузерных clear/opened для B-15 и HTTP-контракта B-01."""

from uuid import UUID

from pydantic import Field

from shared.mvp_contracts.common import ContractModel


class SessionActionRequest(ContractModel):
    """Намерение над показанной сессией; оба ID сохраняются при retry."""

    request_id: UUID = Field(
        description="ID явного действия; при retry сохраняется",
        examples=["22222222-2222-4222-8222-222222222222"],
    )
    expected_session_id: UUID = Field(
        description="ID показанной сессии до подтверждения; не заменяется при retry",
        examples=["11111111-1111-4111-8111-111111111111"],
    )
