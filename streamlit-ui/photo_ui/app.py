"""Управление чатом и жизненным циклом сессии."""

from uuid import uuid4

import streamlit as st
from pydantic import ValidationError

from shared.contracts import ChatMessage, MessageRequest

from .api_client import ApiClient, ApiError
from .design import apply_design, header, sidebar_intro, sidebar_notes, suggestions, welcome
from .lifecycle import mount_close_handler
from .settings import UiSettings
from .state import ChatState


def connect(chat: ChatState, client: ApiClient) -> bool:
    if chat.session_id is not None:
        return True
    try:
        chat.session_id = client.create_session().session_id
        chat.error = None
        return True
    except ApiError, ValidationError:
        st.error("Не удалось открыть чат. Убедитесь, что core-api запущен.")
        if st.button("Подключиться снова"):
            st.rerun()
        return False


def reset(chat: ChatState, client: ApiClient) -> None:
    try:
        if chat.session_id is not None:
            client.delete_session(chat.session_id)
    except ApiError as exc:
        chat.error = str(exc)
        return
    st.session_state.chat = ChatState()
    st.rerun()


def deliver(chat: ChatState, client: ApiClient) -> None:
    if chat.pending is None or chat.session_id is None:
        return
    try:
        with st.spinner("Определяем тему вопроса…"):
            result = client.send(chat.session_id, chat.pending)
        chat.messages.extend(
            [
                ChatMessage(role="user", text=chat.pending.text),
                ChatMessage(role="assistant", text=result.reply),
            ]
        )
        chat.pending = None
        chat.error = None
        st.rerun()
    except ApiError as exc:
        chat.error = str(exc)
        chat.expired = exc.status_code == 404
    except ValidationError:
        chat.error = "Ассистент вернул неожиданный ответ. Попробуйте ещё раз."


def render_pending(chat: ChatState, client: ApiClient) -> None:
    if chat.error:
        st.warning(chat.error)
    if chat.pending is not None:
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(chat.pending.text)
        if not chat.expired and st.button("Повторить отправку"):
            deliver(chat, client)


def maintain_session(chat: ChatState, client: ApiClient, settings: UiSettings) -> None:
    @st.fragment(run_every=settings.heartbeat_seconds)
    def heartbeat() -> None:
        if chat.session_id is None or chat.expired:
            return
        try:
            client.heartbeat(chat.session_id)
        except ApiError as exc:
            if exc.status_code == 404:
                chat.expired = True
                chat.error = str(exc)
                st.rerun()
            st.caption("Связь временно потеряна. Восстанавливаем соединение…")

    if chat.session_id is not None:
        mount_close_handler(str(settings.public_backend_url), chat.session_id)
        heartbeat()


def conversation(chat: ChatState, client: ApiClient) -> None:
    choice = None
    if not chat.messages and chat.pending is None:
        welcome()
        choice = suggestions()
        st.caption("Пока определяем тему вопроса. Разбор снимков и поиск появятся позже.")
    else:
        st.subheader("Ваш разговор о фотографии")
        for message in chat.messages:
            avatar = ":material/camera:" if message.role == "assistant" else ":material/person:"
            with st.chat_message(message.role, avatar=avatar):
                st.markdown(message.text)
    render_pending(chat, client)
    prompt = st.chat_input(
        "Что хочется узнать о фотографии?",
        max_chars=4000,
        disabled=chat.pending is not None or chat.expired,
    )
    text = prompt or choice
    if text and text.strip() and chat.pending is None and not chat.expired:
        chat.pending = MessageRequest(request_id=uuid4(), text=text)
        deliver(chat, client)
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="PhotoAgent — ассистент фотографа",
        page_icon="◉",
        layout="wide",
        initial_sidebar_state="auto",
    )
    apply_design()
    try:
        settings = UiSettings()
    except ValidationError:
        st.error(
            "Не настроено подключение. Задайте PHOTO_UI_BACKEND_URL и PHOTO_UI_PUBLIC_BACKEND_URL."
        )
        st.stop()
    client = ApiClient(settings)
    if "chat" not in st.session_state:
        st.session_state.chat = ChatState()
    chat: ChatState = st.session_state.chat
    with st.sidebar:
        sidebar_intro()
        if st.button("＋  Новый чат", key="new_chat", width="stretch"):
            reset(chat, client)
        sidebar_notes()
    header()
    if not connect(chat, client):
        st.stop()
    maintain_session(chat, client, settings)
    conversation(chat, client)
