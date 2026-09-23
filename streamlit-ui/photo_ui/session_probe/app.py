"""Диагностика cookie → Streamlit → API без вывода токенов."""

from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from .client import ProbeClient, ProbeError, ProbeSettings, ProbeSnapshot

_BROWSER = st.components.v2.component(
    "f01_browser_session",
    html="<div data-f01-controls></div>",
    js=Path(__file__).with_name("browser.js").read_text(encoding="utf-8"),
)


def render_snapshot(settings: ProbeSettings, token: str | None) -> None:
    @st.fragment(run_every=settings.poll_seconds)
    def poll() -> None:
        if not token:
            st.session_state.f01_snapshot = None
            st.info("Cookie сессии отсутствует в текущем подключении Streamlit.")
            return
        try:
            snapshot = ProbeClient(settings).snapshot(token)
            st.session_state.f01_snapshot = snapshot
            st.success("Токен из cookie принят API через серверный HTTP-клиент.")
        except ProbeError as exc:
            if exc.unavailable:
                st.session_state.f01_snapshot = None
                st.warning("Сессия отозвана или истекла. Локальная копия очищена.")
            else:
                st.warning("Связь с API не подтверждена. Последний снимок может быть устаревшим.")
        snapshot: ProbeSnapshot | None = st.session_state.f01_snapshot
        if snapshot is not None:
            st.json(snapshot.diagnostic())

    poll()


def main() -> None:
    st.set_page_config(page_title="PhotoAgent · F-01", layout="centered")
    st.title("F-01 · Проверка браузерной сессии")
    st.caption("Исследовательский стенд. Только синтетические данные; это не чат MVP-1.")
    try:
        settings = ProbeSettings()
    except ValidationError:
        st.error("Задайте PHOTO_F01_BACKEND_URL и проверьте настройки PHOTO_F01_*.")
        return
    if "f01_snapshot" not in st.session_state:
        st.session_state.f01_snapshot = None
    token = st.context.cookies.get(settings.cookie_name)
    st.write("Cookie в подключении Streamlit:", "есть" if token else "нет")
    _BROWSER(key="f01_browser", data={"timeout_ms": settings.request_timeout_seconds * 1000})
    render_snapshot(settings, token)
    st.caption(
        "Опрос только читает состояние. Refresh должен продлевать TTL, автоматический "
        "reconnect — сохранять его. После изменения cookie требуется новое подключение."
    )
