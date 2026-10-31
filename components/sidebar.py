"""Custom workspace navigation and account controls."""

from __future__ import annotations

import html

import streamlit as st
from sqlalchemy import select

from config import settings
from database.db import session_scope
from database.models import Teacher
from pages._common import teacher_id


def render_sidebar(pages: dict[str, object]) -> bool:
    with session_scope() as session:
        teacher = session.get(Teacher, teacher_id(session))
        if teacher is None:
            raise PermissionError("The signed-in teacher workspace is unavailable.")
        name = teacher.name
        email = teacher.email
        demo_account = teacher.is_demo_account
        initials = "".join(part[0].upper() for part in name.split()[:2]) or "T"
    with st.sidebar:
        st.markdown("""
        <div class="brand-lockup">
          <div class="brand-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4.5h14v15H5z"/><path d="M8.5 8h7M8.5 11.5h7M8.5 15h4"/><path d="m15.5 16 1.5 1.5 3-3"/></svg></div>
          <div><div class="brand-name">PaperGrade <span>AI</span></div><div class="brand-caption">AI assessment workspace</div></div>
        </div>
        """, unsafe_allow_html=True)
        if demo_account:
            st.markdown("<div class='nav-section-label'>DEMO WORKSPACE · FIXTURE DATA ONLY</div>", unsafe_allow_html=True)
            st.session_state.workspace_mode = "demo"
        else:
            mode_names = ["Demonstration mode", "Live Gemma mode"]
            if "workspace_mode_radio" not in st.session_state:
                st.session_state.workspace_mode_radio = "Demonstration mode" if st.session_state.get("workspace_mode", "demo") == "demo" else "Live Gemma mode"
            selected = st.radio("WORKSPACE MODE", mode_names, key="workspace_mode_radio", label_visibility="visible")
            st.session_state.workspace_mode = "demo" if selected == mode_names[0] else "live"
        demo = st.session_state.workspace_mode == "demo"
        st.markdown("<div class='nav-section-label'>OVERVIEW</div>", unsafe_allow_html=True)
        st.page_link(pages["Welcome"], label="Welcome", icon=":material/waving_hand:")
        st.page_link(pages["Dashboard"], label="Dashboard", icon=":material/dashboard:")
        st.markdown("<div class='nav-section-label'>ASSESSMENT</div>", unsafe_allow_html=True)
        st.page_link(pages["New Evaluation"], label="New evaluation", icon=":material/add_task:")
        st.page_link(pages["Evaluation History"], label="Evaluation history", icon=":material/history:")
        st.markdown("<div class='nav-section-label'>MANAGEMENT</div>", unsafe_allow_html=True)
        st.page_link(pages["Students"], label="Students", icon=":material/group:")
        st.page_link(pages["Analytics"], label="Analytics", icon=":material/monitoring:")
        st.markdown("<div class='nav-section-label'>PREFERENCES</div>", unsafe_allow_html=True)
        st.page_link(pages["Settings"], label="Settings", icon=":material/settings:")
        if st.session_state.get("selected_evaluation_id"):
            st.markdown("<div class='nav-section-label'>CURRENT ASSESSMENT</div>", unsafe_allow_html=True)
            st.page_link(pages["Evaluation Review"], label="Evaluation review", icon=":material/rate_review:")
        st.markdown("<div class='sidebar-spacer'></div>", unsafe_allow_html=True)
        st.markdown(f"""
        <div class="profile-card"><div class="avatar">{html.escape(initials)}</div><div class="profile-copy"><strong>{html.escape(name)}</strong><span>{html.escape(email)}</span></div><span class="profile-dot"></span></div>
        """, unsafe_allow_html=True)
        st.markdown(f"<div class='sidebar-version'>PAPERGRADE AI · v1.0.0<br>{'DEMO DATA IS LABELED' if demo else 'LIVE WORKSPACE'}</div>", unsafe_allow_html=True)
        if st.button("Log out", key="teacher_logout", use_container_width=True):
            from pages.auth import logout
            logout()
    return demo

