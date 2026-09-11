"""Попытка завершить сессию при закрытии вкладки; TTL остаётся страховкой."""

from pathlib import Path
from uuid import UUID

import streamlit as st

_CLOSE_COMPONENT = st.components.v2.component(
    "session_lifecycle",
    html='<span data-photo-lifecycle="loading" hidden></span>',
    js=Path(__file__).with_name("lifecycle.js").read_text(),
)


def mount_close_handler(public_backend_url: str, session_id: UUID) -> None:
    _CLOSE_COMPONENT(
        data={"url": f"{public_backend_url.rstrip('/')}/sessions/{session_id}/close"},
        key=f"close_{session_id}",
    )
