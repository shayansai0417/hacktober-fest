"""PaperGrade AI · authenticated teacher assessment workspace."""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st
from sqlalchemy import select

from components.sidebar import render_sidebar
from config import ROOT_DIR, settings
from database.db import init_db, session_scope
from database.models import AuthSession, Teacher, utcnow
from database.seed import seed_demo
from pages import analytics, auth, dashboard, history, new_evaluation, review, settings as settings_page, students, welcome


st.set_page_config(page_title="PaperGrade AI · Assessment Workspace", page_icon="assets/logo.svg", layout="wide", initial_sidebar_state="auto")
settings.validate_production_configuration()


@st.cache_resource(show_spinner=False)
def _initialize() -> bool:
    init_db()
    with session_scope() as session:
        from services.auth_service import cleanup_auth_artifacts
        cleanup_auth_artifacts(session)
        seed_demo(session)
    return True


_initialize()
css_path = ROOT_DIR / "assets" / "styles.css"
st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

routes = {
    "Welcome": st.Page(welcome.render, title="Welcome", icon=":material/waving_hand:", url_path="welcome", default=True),
    "Dashboard": st.Page(dashboard.render, title="Dashboard", icon=":material/dashboard:", url_path="dashboard"),
    "New Evaluation": st.Page(new_evaluation.render, title="New evaluation", icon=":material/add_task:", url_path="new-evaluation"),
    "Evaluation History": st.Page(history.render, title="Evaluation history", icon=":material/history:", url_path="history"),
    "Students": st.Page(students.render, title="Students", icon=":material/group:", url_path="students"),
    "Analytics": st.Page(analytics.render, title="Analytics", icon=":material/monitoring:", url_path="analytics"),
    "Settings": st.Page(settings_page.render, title="Settings", icon=":material/settings:", url_path="settings"),
    "Evaluation Review": st.Page(review.render, title="Evaluation review", icon=":material/rate_review:", url_path="review"),
}
st.session_state.page_objects = routes

# Register hidden routes before rendering sign-in so a successful browser
# redirect can reopen the requested protected page.
navigation = st.navigation(list(routes.values()), position="hidden")

# Verification and recovery links are public entry points, even when a browser
# already has another teacher's active session cookie.
if st.query_params.get("auth_action"):
    auth.render()
    st.stop()


def _authenticated_teacher() -> Teacher | None:
    auth.restore_browser_session()
    teacher_id = st.session_state.get("auth_teacher_id")
    auth_session_id = st.session_state.get("auth_login_session_id")
    expires_at = st.session_state.get("auth_expires_at")
    if not teacher_id or not auth_session_id or not expires_at:
        return None
    try:
        expiry = datetime.fromisoformat(expires_at)
    except (TypeError, ValueError):
        expiry = datetime.min.replace(tzinfo=timezone.utc)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc):
        _clear_auth_state("Your session expired. Sign in again to continue.")
        return None
    with session_scope() as session:
        auth_session = session.get(AuthSession, auth_session_id)
        teacher = session.scalar(select(Teacher).where(Teacher.id == teacher_id))
        auth_expiry = auth_session.expires_at if auth_session else None
        if auth_expiry and auth_expiry.tzinfo is None:
            auth_expiry = auth_expiry.replace(tzinfo=timezone.utc)
        if (auth_session is None or auth_session.teacher_id != teacher_id or auth_session.revoked_at is not None
                or auth_expiry is None or auth_expiry <= utcnow()
                or teacher is None or teacher.session_version != st.session_state.get("auth_session_version")
                or auth_session.session_version != teacher.session_version
                or (teacher.is_demo_account and not settings.demo_login_available)):
            teacher = None
        if teacher is not None:
            state = {
                "id": teacher.id,
                "name": teacher.name,
                "email": teacher.email,
                "is_demo_account": teacher.is_demo_account,
                "session_version": teacher.session_version,
            }
        else:
            state = None
    if state is None:
        _clear_auth_state("Your session is no longer valid. Sign in again.")
        return None
    st.session_state.auth_teacher_name = state["name"]
    st.session_state.auth_teacher_email = state["email"]
    st.session_state.auth_is_demo = state["is_demo_account"]
    st.session_state.gemma_ready = settings.live_ready
    if state["is_demo_account"]:
        # The public example account can only access explicitly labeled fixtures.
        st.session_state.workspace_mode = "demo"
    else:
        st.session_state.setdefault("workspace_mode", "demo" if settings.demo_mode else "live")
    return None


def _clear_auth_state(message: str | None = None) -> None:
    had_session = bool(st.session_state.get("auth_login_session_id"))
    for key in ("auth_teacher_id", "auth_login_session_id", "auth_session_version", "auth_expires_at", "auth_teacher_name", "auth_teacher_email", "auth_is_demo"):
        st.session_state.pop(key, None)
    if had_session:
        st.session_state._auth_cookie_invalid = True
    if message:
        st.session_state.auth_flash = message


_authenticated_teacher()
if not st.session_state.get("auth_teacher_id"):
    auth.render()
    if not st.session_state.get("auth_teacher_id"):
        st.stop()

st.session_state.setdefault("workspace_mode", "demo" if settings.demo_mode else "live")
pending_mode = st.session_state.pop("_pending_workspace_mode", None)
if st.session_state.get("auth_is_demo"):
    st.session_state.workspace_mode = "demo"
    st.session_state.workspace_mode_radio = "Demonstration mode"
elif pending_mode in {"demo", "live"}:
    # Apply programmatic mode changes before the sidebar radio is instantiated.
    st.session_state.workspace_mode = pending_mode
    st.session_state.workspace_mode_radio = "Demonstration mode" if pending_mode == "demo" else "Live Gemma mode"
elif "workspace_mode_radio" not in st.session_state:
    st.session_state.workspace_mode_radio = "Demonstration mode" if st.session_state.workspace_mode == "demo" else "Live Gemma mode"

render_sidebar(routes)
navigation.run()
