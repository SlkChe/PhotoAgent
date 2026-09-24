"""Предлагаемые HTTP-тела B-01; ограничения продукта требуют согласования."""

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from shared.mvp_contracts.answer import AnswerStyle
from shared.mvp_contracts.common import ContractModel, Locale, Revision, Text, UtcDatetime


class DraftEnvelope(ContractModel):
    contract_version: Literal["mvp1-http-draft.1"] = Field(
        description="Несогласованный HTTP-конверт; не версия предметного Answer",
        examples=["mvp1-http-draft.1"],
    )


class SettingsValue(AnswerStyle):
    locale: Locale = Field(description="Локаль будущих отправок", examples=["ru"])


class OperationRequest(ContractModel):
    request_id: UUID = Field(
        description="ID явного действия; при retry сохраняется",
        examples=["22222222-2222-4222-8222-222222222222"],
    )


class SettingsUpdate(OperationRequest):
    expected_settings_revision: Revision = Field(description="Версия только настроек", examples=[0])
    settings: SettingsValue = Field(description="Полный целевой набор настроек")


class SettingsReceipt(DraftEnvelope):
    request_id: UUID = Field(
        description="Подтверждённое действие", examples=["22222222-2222-4222-8222-222222222222"]
    )
    settings_revision: Revision = Field(description="Версия после действия", examples=[1])
    settings: SettingsValue = Field(description="Принятый набор настроек")


class MessageRequest(OperationRequest):
    text: Text = Field(
        description="Исходный текст; предел длины приходит в capabilities",
        examples=["Что такое диафрагма?"],
    )
    settings_revision: Revision = Field(
        description="Версия настроек на момент первой отправки", examples=[0]
    )
    settings: SettingsValue = Field(description="Неизменный снимок настройки для retry")
    clarification_id: Text | None = Field(
        description="Ответ на ожидаемое уточнение; иначе null", examples=[None]
    )


class CancelClarification(OperationRequest):
    clarification_id: Text = Field(
        description="Какое ожидаемое уточнение отменить", examples=["clarification-1"]
    )


class BrowserContext(DraftEnvelope):
    session_id: UUID | None = Field(
        description="ID только доступной сессии, не bearer", examples=[None]
    )
    csrf_token: Text = Field(
        description="Привязан к HttpOnly-контексту; не токен сессии", examples=["synthetic-csrf"]
    )


class RoleRef(ContractModel):
    role_id: Text = Field(
        description="Стабильный ID из реестра ролей; список требует A-13", examples=["friend"]
    )
    display_name: Text = Field(
        min_length=1,
        max_length=20,
        description="Подпись на момент ответа, до 20 Unicode code points",
        examples=["Друг"],
    )


class FeedbackUpdate(OperationRequest):
    expected_feedback_revision: Revision = Field(
        description="Версия отзыва конкретного ответа", examples=[0]
    )
    rating: Literal["positive", "negative"] = Field(
        description="Только явная оценка", examples=["negative"]
    )
    comment: Text | None = Field(
        description="Необязательный комментарий при negative; null удаляет",
        examples=["Недостаточно примеров", None],
    )

    @model_validator(mode="after")
    def comment_for_negative(self) -> Self:
        if self.rating != "negative" and self.comment is not None:
            raise ValueError("Комментарий разрешён только для negative")
        return self


class AnswerState(ContractModel):
    answer_id: UUID = Field(
        description="Ответ в текущей сессии", examples=["66666666-6666-4666-8666-666666666666"]
    )
    eligible: StrictBool = Field(
        description="Оценка допустима для answer/insufficient_evidence", examples=[True]
    )
    shown: StrictBool = Field(
        description="UI подтвердил показ; повтор не учитывается", examples=[False]
    )
    feedback_revision: Revision = Field(
        description="Версия только оценки/комментария", examples=[0]
    )
    rating: Literal["no_feedback", "positive", "negative"] = Field(
        description="no_feedback не выглядит поставленным лайком", examples=["no_feedback"]
    )
    comment: Text | None = Field(
        description="Только RAM живой сессии; при positive null", examples=[None]
    )

    @model_validator(mode="after")
    def eligibility(self) -> Self:
        if self.comment is not None and self.rating != "negative":
            raise ValueError("Комментарий разрешён только для negative")
        if not self.eligible and (self.shown or self.rating != "no_feedback"):
            raise ValueError("Служебный ответ не входит в учёт отзывов")
        if self.rating != "no_feedback" and not self.shown:
            raise ValueError("Оценка требует подтверждённого показа")
        return self


class FeedbackReceipt(DraftEnvelope):
    request_id: UUID = Field(
        description="ID принятого изменения", examples=["22222222-2222-4222-8222-222222222222"]
    )
    state: AnswerState = Field(description="Состояние после изменения; при retry прежняя квитанция")


class ExportPrepare(OperationRequest):
    expected_revision: Revision = Field(
        description="Версия всего snapshot, которую видел пользователь", examples=[3]
    )


class ExportReady(DraftEnvelope):
    export_id: UUID = Field(
        description="ID двух файлов одного снимка; сам по себе не авторизация",
        examples=["88888888-8888-4888-8888-888888888888"],
    )
    snapshot_revision: Revision = Field(description="Зафиксированная версия диалога", examples=[3])
    expires_at: UtcDatetime = Field(
        description="Не позднее expires_at сессии", examples=["2026-09-24T10:01:00Z"]
    )
    available: list[Literal["dialogue", "sources"]] = Field(
        min_length=1,
        description="Разрешённые файлы; пустое содержимое не предлагается",
        examples=[["dialogue", "sources"]],
    )
    incomplete_execution: StrictBool = Field(
        description="Включена отметка о незавершённом ответе", examples=[False]
    )


class ErrorCount(ContractModel):
    code: Text = Field(
        description="Безопасная категория, без текста запроса/исключения",
        examples=["provider_error"],
    )
    count: Revision = Field(description="Число ошибок", examples=[0])


class DayStats(ContractModel):
    day: date = Field(description="Календарный день UTC", examples=["2026-09-24"])
    completeness: Literal["complete", "partial", "unknown"] = Field(
        description="Надёжность периода; точная семантика требует A-08", examples=["unknown"]
    )
    shown_answers: Revision = Field(
        description="Уникальные показанные оцениваемые ответы", examples=[1]
    )
    positive: Revision = Field(description="Явные положительные оценки", examples=[1])
    negative: Revision = Field(description="Явные отрицательные оценки", examples=[0])
    no_feedback: Revision = Field(
        description="Итоговые без отклика, отдельно от positive", examples=[0]
    )
    pending_feedback: Revision = Field(description="Ещё не оценённые в живых сессиях", examples=[0])
    technical_errors: list[ErrorCount] = Field(
        description="Агрегаты без персональных меток", examples=[[]]
    )

    @model_validator(mode="after")
    def counts(self) -> Self:
        if (
            self.shown_answers
            != self.positive + self.negative + self.no_feedback + self.pending_feedback
        ):
            raise ValueError("Число показанных ответов не совпадает с категориями")
        return self


class StatsReport(DraftEnvelope):
    generated_at: UtcDatetime = Field(
        description="Время снимка отчёта UTC", examples=["2026-09-24T10:00:00Z"]
    )
    from_date: date = Field(description="Начало включительно", examples=["2026-09-24"])
    to_date: date = Field(description="Конец включительно", examples=["2026-09-24"])
    days: list[DayStats] = Field(
        description="Дневные агрегаты; неизвестный день не изображается нулём"
    )

    @model_validator(mode="after")
    def period(self) -> Self:
        dates = [item.day for item in self.days]
        if self.from_date > self.to_date or dates != sorted(set(dates)):
            raise ValueError("Некорректный период или повтор дня")
        if any(not self.from_date <= day <= self.to_date for day in dates):
            raise ValueError("День вне периода")
        return self
