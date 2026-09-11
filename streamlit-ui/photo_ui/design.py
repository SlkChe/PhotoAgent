"""Отрисовка статических элементов концепта."""

from pathlib import Path

import streamlit as st


def apply_design() -> None:
    css = Path(__file__).with_name("style.css").read_text()
    st.html(f"<style>{css}</style>")


def sidebar_intro() -> None:
    st.html("""
        <div class="brand"><span class="brand-icon">◉</span> PhotoAgent</div>
        <div class="brand-caption">АССИСТЕНТ ФОТОГРАФА</div>
    """)


def sidebar_notes() -> None:
    st.html("""
        <div class="sidebar-note">
          <div class="eyebrow">ОТ ИДЕИ К КАДРУ</div>
          <p>Разбирайтесь в свете.<br>Находите своё видение.<br>Задавайте вопросы.</p>
        </div>
        <div class="sidebar-bottom"><span class="status-dot"></span>
          Прототип · 0.1<br><small>Каждый разговор — с чистого листа.</small></div>
    """)


def header() -> None:
    st.html("""
        <div class="topline"><span>ВАША ТВОРЧЕСКАЯ ПРАКТИКА</span>
          <span class="edition">PHOTO / 01</span></div>
    """)


def welcome() -> None:
    st.html("""
        <div class="hero">
          <div class="eyebrow">МЕСТО ДЛЯ ВАШИХ ВОПРОСОВ</div>
          <h1>Хороший кадр<br>начинается с <em>вопроса.</em></h1>
          <p>Поговорим о фотографии? Начните со своей идеи<br class="desktop-break">
             или выберите, что хочется исследовать.</p>
        </div>
    """)


def suggestions() -> str | None:
    cards = [
        ("01 / ТЕОРИЯ", "Понять свет и композицию", "Объясни глубину резкости"),
        ("02 / ПОИСК", "Найти технику или студию", "Найди студию для портретной съёмки"),
        ("03 / КАДР", "Обсудить конкретный снимок", "Почему на этом кадре смазан фон?"),
        ("04 / ДИАЛОГ", "Продолжить разговор", "Да, продолжай"),
    ]
    selected = None
    for offset in (0, 2):
        for column, (number, title, prompt) in zip(st.columns(2), cards[offset : offset + 2]):
            with column, st.container(border=True):
                st.caption(number)
                st.markdown(f"**{title}**")
                if st.button(prompt + "  ↗", key=f"suggestion_{offset}_{number}", width="stretch"):
                    selected = prompt
    return selected
