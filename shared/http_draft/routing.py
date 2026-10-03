"""Внутренний выбор профилей и авторства A-13; не публичный ответ API."""

from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from shared.mvp_contracts.answer import Answer
from shared.mvp_contracts.common import ContractModel, Revision, Text, unique
from shared.mvp_contracts.query import QueryAnalysis

from .operations import RoleRef

if TYPE_CHECKING:
    from .session import ExecutionView


class SubquestionRole(ContractModel):
    subquestion_id: Text = Field(description="ID допустимого подвопроса анализа", examples=["q1"])
    role: RoleRef = Field(description="Профиль содержания подвопроса, не отдельный агент")


class RoutingDecision(ContractModel):
    session_id: UUID = Field(description="Сессия исходного выполнения", examples=[str(UUID(int=1))])
    request_id: UUID = Field(description="Исходный запрос", examples=[str(UUID(int=2))])
    execution_id: UUID = Field(description="Исходное выполнение", examples=[str(UUID(int=3))])
    base_revision: Revision = Field(description="Версия контекста анализа", examples=[0])
    selected_role: RoleRef = Field(description="Ведущий профиль содержания")
    mode: Literal["single", "consolidated"] = Field(
        description="Один ведущий либо координация равнозначных задач", examples=["single"]
    )
    subquestion_roles: list[SubquestionRole] = Field(
        description="Каждый допустимый подвопрос назначен ровно одному профилю", examples=[[]]
    )
    author_role: RoleRef = Field(description="Будущая неизменная подпись ответа")
    author_basis: Literal["selected", "first_addressed", "coordinator"] = Field(
        description="Основание подписи, не свободные рассуждения", examples=["selected"]
    )
    addressed_roles: list[RoleRef] = Field(
        description="Известные адресаты по порядку без повторов/цитат/отрицаний", examples=[[]]
    )
    main_subquestion_id: Text | None = Field(
        description="Главная задача; null для invitation, общего обзора, консолидации",
        examples=[None],
    )
    route_basis: Literal[
        "explicit_role",
        "main_task",
        "topic",
        "boundary_friend",
        "context_rephrase",
        "equal_tasks",
        "unknown_role_invitation",
    ] = Field(description="Проверяемое основание выбора", examples=["topic"])

    @model_validator(mode="after")
    def roles(self) -> Self:
        """Проверяет локальные инварианты без ложного равенства ведущего и автора."""
        unique([r.role_id for r in self.addressed_roles], "addressed_roles")
        unique([r.subquestion_id for r in self.subquestion_roles], "subquestion_roles")
        if self.main_subquestion_id is not None and self.main_subquestion_id not in {
            r.subquestion_id for r in self.subquestion_roles
        }:
            raise ValueError("Главный подвопрос не назначен профилю")
        if self.mode == "consolidated":
            if (
                self.selected_role.role_id != "friend"
                or self.author_role != self.selected_role
                or self.author_basis != "coordinator"
                or self.main_subquestion_id is not None
                or self.route_basis != "equal_tasks"
            ):
                raise ValueError("Консолидацию ведёт и подписывает Друг без главного подвопроса")
            if len({r.role.role_id for r in self.subquestion_roles}) < 2:
                raise ValueError("Консолидация требует подвопросов разных профилей")
        elif self.author_basis == "coordinator" or self.route_basis == "equal_tasks":
            raise ValueError("Координация равнозначных задач требует consolidated")
        if self.author_basis == "selected" and self.author_role != self.selected_role:
            raise ValueError("Подпись selected должна соответствовать ведущему")
        if self.author_basis == "first_addressed":
            if (
                len(self.addressed_roles) < 2
                or self.author_role != self.addressed_roles[0]
                or self.main_subquestion_id is None
                or self.route_basis != "main_task"
            ):
                raise ValueError("Подпись первого требует нескольких адресатов и главной задачи")
        if self.route_basis == "unknown_role_invitation":
            if (
                self.selected_role.role_id != "friend"
                or self.author_basis != "selected"
                or self.subquestion_roles
                or self.main_subquestion_id is not None
                or self.addressed_roles
            ):
                raise ValueError("Неизвестная роль без вопроса получает invitation Друга")
        return self

    def validate_analysis(self, analysis: QueryAnalysis, *, revision: int) -> None:
        """Сверяет доверенную принадлежность, версию и полное покрытие анализа."""
        if (self.session_id, self.request_id, self.execution_id) != (
            analysis.session_id,
            analysis.request_id,
            analysis.execution_id,
        ):
            raise ValueError("Маршрутизация другого выполнения")
        if self.base_revision != revision or analysis.context_update.base_revision != revision:
            raise ValueError("Устаревший контекст маршрутизации")
        if {r.subquestion_id for r in self.subquestion_roles} != {
            q.id for q in analysis.subquestions
        }:
            raise ValueError("Профили должны покрывать все и только допустимые подвопросы")

    def validate_publication(self, answer: Answer, *, author: RoleRef) -> None:
        """Связывает опубликованный ответ с сохранённой подписью маршрутизации."""
        if (self.session_id, self.request_id, self.execution_id) != (
            answer.session_id,
            answer.request_id,
            answer.execution_id,
        ) or author != self.author_role:
            raise ValueError("Публикация не соответствует выполнению или сохранённому автору")
        if answer.kind == "invitation" and self.subquestion_roles:
            raise ValueError("Invitation не содержит содержательных подвопросов")
        if self.route_basis == "unknown_role_invitation" and answer.kind != "invitation":
            raise ValueError("Неизвестная роль без вопроса требует invitation")

    def validate_execution(self, view: ExecutionView) -> None:
        """Сверяет публичное выполнение с сохранённым внутренним выбором."""
        if (view.session_id, view.execution.request_id, view.execution.execution_id) != (
            self.session_id,
            self.request_id,
            self.execution_id,
        ) or view.execution.selected_role != self.selected_role:
            raise ValueError("Публичное выполнение не соответствует маршрутизации")
        if view.answer is not None and view.author is not None:
            self.validate_publication(view.answer, author=view.author)
