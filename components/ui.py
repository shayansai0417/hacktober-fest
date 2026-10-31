"""Small HTML presentation helpers shared across pages."""

from __future__ import annotations

import html

import streamlit as st


def page_header(title: str, subtitle: str, eyebrow: str = "") -> None:
    if eyebrow:
        st.markdown(f"<div class='eyebrow'>{html.escape(eyebrow)}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='page-title-row'><div><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div></div>", unsafe_allow_html=True)


def badge(label: str, tone: str = "neutral") -> str:
    return f"<span class='badge badge-{tone}'>{html.escape(label)}</span>"


def empty_state(title: str, description: str) -> None:
    st.markdown(f"<div class='empty-state'><div class='empty-icon'>◎</div><h3>{html.escape(title)}</h3><p>{html.escape(description)}</p></div>", unsafe_allow_html=True)

