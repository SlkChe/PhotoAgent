"""Просмотр готовой оболочки на синтетических состояниях без сетевых вызовов."""

from uuid import uuid4

import streamlit as st

from .component import render_layout
from .models import LayoutView, MessageView, SourceView


def sample_view(history: bool) -> LayoutView:
    view = LayoutView(session_key="layout-preview")
    if not history:
        return view
    view.current_role = "Историк фотографии"
    for index in range(12):
        view.messages.extend(
            [
                MessageView(
                    message_id=f"user-{index}",
                    kind="user",
                    text=f"Учебный вопрос {index + 1}: как смотреть фотографии мастеров?",
                ),
                MessageView(
                    message_id=f"answer-{index}",
                    kind="assistant",
                    author="Историк фотографии",
                    text="Начните с сюжета, света и композиции. Сравните несколько снимков серии. "
                    "Это синтетический текст для просмотра компоновки, не ответ сервиса.",
                ),
            ]
        )
        view.sources.append(
            SourceView(
                card_id=f"card-{index}",
                title=f"Учебный материал {index + 1}",
                url=f"https://example.org/photography/{index + 1}",
                context_comment="Как смотреть фотографии мастеров?",
                first_message_id=f"answer-{index}",
            )
        )
    return view


def main() -> None:
    st.set_page_config(page_title="PhotoAgent · компоновка", layout="wide")
    st.html(
        "<style>.stMainBlockContainer{padding:1rem;max-width:none}"
        "[data-testid='stHeader']{display:none}</style>"
    )
    st.caption("Просмотр F-07 · синтетические данные · API и генерация не вызываются")
    scenario = st.selectbox(
        "Состояние", ["Новый диалог", "Длинный диалог", "Ожидание", "Нет связи"]
    )
    if "layout_view" not in st.session_state or st.session_state.get("layout_scenario") != scenario:
        st.session_state.layout_view = sample_view(scenario != "Новый диалог")
        st.session_state.layout_scenario = scenario
    view: LayoutView = st.session_state.layout_view
    view.input_disabled = scenario in ("Ожидание", "Нет связи")
    view.settings_disabled = view.input_disabled
    view.status = {"Ожидание": "Готовлю ответ", "Нет связи": "Восстанавливаем соединение…"}.get(
        scenario, ""
    )
    event = render_layout(view)
    if event is None:
        return
    if event.action == "send" and not view.input_disabled:
        view.messages.append(MessageView(message_id=str(uuid4()), kind="user", text=event.text))
        view.draft_revision += 1
    elif event.action == "settings" and not view.settings_disabled:
        view.detail, view.level = event.detail, event.level
    st.rerun()
