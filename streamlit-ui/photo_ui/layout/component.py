"""Streamlit-компонент с сохранением черновика между rerun."""

from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from .models import LayoutEvent, LayoutView

_DIRECTORY = Path(__file__).parent
_SHELL = st.components.v2.component(
    "photoagent_dialogue_layout",
    html=(_DIRECTORY / "shell.html").read_text(encoding="utf-8"),
    css=(_DIRECTORY / "shell.css").read_text(encoding="utf-8"),
    js=(_DIRECTORY / "shell.js").read_text(encoding="utf-8"),
)


def _changed() -> None:
    pass


def render_layout(view: LayoutView, key: str = "dialogue_shell") -> LayoutEvent | None:
    draft_key = f"{key}_draft"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = ""
    result = _SHELL(
        key=key,
        data={
            "view": view.model_dump(mode="json"),
            "draft": st.session_state[draft_key],
            "instance_key": key,
        },
        default={"draft": st.session_state[draft_key], "action": None},
        on_draft_change=_changed,
        on_action_change=_changed,
    )
    if isinstance(result.draft, str):
        st.session_state[draft_key] = result.draft
    if result.action is None:
        return None
    try:
        event = LayoutEvent.model_validate(result.action)
    except ValidationError:
        return None
    handled_key = f"{key}_handled_event"
    if st.session_state.get(handled_key) == event.event_id:
        return None
    st.session_state[handled_key] = event.event_id
    return event
