"""Workspace, model, and storage configuration overview."""

from __future__ import annotations

import html
import streamlit as st
from sqlalchemy import func, select, text

from components.ui import page_header
from config import settings
from database.db import engine, session_scope
from database.models import Teacher
from pages._common import teacher_id
from services.auth_service import change_password, delete_teacher_workspace, remove_deleted_uploads


def render() -> None:
    page_header("Settings", "Keep workspace preferences and model configuration clear.", "PREFERENCES")
    with session_scope() as session:
        teacher = session.get(Teacher, teacher_id(session))
        profile = {"name": teacher.name, "institution": teacher.institution, "email": teacher.email, "designation": teacher.designation, "subject_specialization": teacher.subject_specialization, "feedback_style": teacher.feedback_style, "grading_strictness": teacher.grading_strictness, "manual_review_required": teacher.manual_review_required, "is_demo_account": teacher.is_demo_account}
    left, right = st.columns(2)
    with left:
        st.markdown("<div class='section-heading compact'><div><h2>Teacher profile</h2><p>Shown on assessment reports</p></div></div>", unsafe_allow_html=True)
        with st.form("profile_settings"):
            name = st.text_input("Teacher name", value=profile["name"])
            institution = st.text_input("Institution", value=profile["institution"])
            designation = st.text_input("Designation", value=profile["designation"])
            specialization = st.text_input("Subject specialization", value=profile["subject_specialization"])
            email = st.text_input("Account email", value=profile["email"], disabled=settings.require_email_verification or settings.app_env.casefold() in {"production", "prod"})
            save = st.form_submit_button("Save profile", type="primary")
        if save:
            try:
                if not name.strip():
                    raise ValueError("Teacher name is required.")
                with session_scope() as session:
                    teacher = session.get(Teacher, teacher_id(session))
                    if email.strip().casefold() != teacher.email.casefold():
                        duplicate = session.scalar(select(Teacher.id).where(func.lower(Teacher.email) == email.strip().casefold(), Teacher.id != teacher.id))
                        if duplicate:
                            raise ValueError("That email is already in use by another teacher account.")
                        teacher.email = email.strip().casefold()
                    teacher.name, teacher.institution = name.strip(), institution.strip()
                    teacher.designation, teacher.subject_specialization = designation.strip(), specialization.strip()
                st.success("Profile saved.")
            except ValueError as exc:
                st.error(str(exc))
        st.markdown("<div class='section-heading compact'><div><h2>Grading preferences</h2><p>Applied to instructions for new live evaluations</p></div></div>", unsafe_allow_html=True)
        with st.form("grading_preferences"):
            feedback_choices = ["Constructive and concise", "Detailed coaching", "Formal and academic"]
            feedback_style = st.selectbox("Feedback style", feedback_choices, index=feedback_choices.index(profile["feedback_style"]) if profile["feedback_style"] in feedback_choices else 0)
            strict_choices = ["Flexible", "Balanced", "Strict"]
            grading_strictness = st.select_slider("Grading strictness", options=strict_choices, value=profile["grading_strictness"] if profile["grading_strictness"] in strict_choices else "Balanced")
            manual_review_required = st.checkbox("Require manual review when handwriting is unclear", value=profile["manual_review_required"])
            save_preferences = st.form_submit_button("Save grading preferences", type="primary")
        if save_preferences:
            with session_scope() as session:
                teacher = session.get(Teacher, teacher_id(session))
                teacher.feedback_style, teacher.grading_strictness, teacher.manual_review_required = feedback_style, grading_strictness, manual_review_required
            st.success("Grading preferences saved.")
        st.caption("The teacher's marking scheme remains the source of truth for every score.")
        st.markdown("<div class='section-heading compact'><div><h2>Account security</h2><p>Change your password or sign out other sessions</p></div></div>", unsafe_allow_html=True)
        if not profile["is_demo_account"]:
            with st.form("change_password"):
                old_password = st.text_input("Current password", type="password")
                new_password = st.text_input("New password", type="password", help="Use at least 12 characters.")
                confirm_password = st.text_input("Confirm new password", type="password")
                change = st.form_submit_button("Change password", type="primary")
            if change:
                if new_password != confirm_password:
                    st.error("The passwords do not match.")
                else:
                    try:
                        with session_scope() as session:
                            teacher = session.get(Teacher, teacher_id(session))
                            change_password(session, teacher, old_password, new_password, keep_session_id=st.session_state.get("auth_login_session_id"))
                            st.session_state.auth_session_version = teacher.session_version
                        st.success("Password updated. Other active sessions have been signed out.")
                    except ValueError as exc:
                        st.error(str(exc))
            with st.expander("Delete teacher account and its workspace"):
                st.warning("Deleting your account permanently removes its students, assessments, uploaded pages, and review history.")
                typed_confirmation = st.text_input("Type DELETE to confirm", key="delete_account_confirmation")
                current_password = st.text_input("Confirm your password", type="password", key="delete_account_password")
                if st.button("Delete account permanently", type="primary", disabled=typed_confirmation != "DELETE"):
                    try:
                        deleted_uploads = []
                        with session_scope() as session:
                            deleted_uploads = delete_teacher_workspace(session, teacher_id(session), current_password)
                        remove_deleted_uploads(deleted_uploads)
                        from pages.auth import logout
                        logout()
                    except (PermissionError, ValueError) as exc:
                        st.error(str(exc))
        else:
            st.info("The shared demo account is read-only for account credentials. Its example password is shown on the sign-in screen.")
    with right:
        st.markdown("<div class='section-heading compact'><div><h2>AI configuration</h2><p>Live grading uses the configured Gemma model</p></div></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='settings-info'><span>MODEL ID</span><strong>{html.escape(settings.gemma_model)}</strong><small>Google Gemma 4 · image and text input</small></div>", unsafe_allow_html=True)
        if settings.live_ready:
            st.success("Gemma API key is configured. The key is not displayed in the app.")
        else:
            st.warning("No GEMMA_API_KEY detected. Demonstration mode is available without a key.")
        st.caption("Manage the API key in your local environment configuration, then restart PaperGrade AI. Secret values stay hidden here.")
        st.markdown("<div class='section-heading compact'><div><h2>System health</h2><p>Current deployment details</p></div></div>", unsafe_allow_html=True)
        try:
            with engine.connect() as connection: connection.execute(text("SELECT 1"))
            db_status = "Connected"
        except Exception: db_status = "Unavailable"
        values = [("Database", db_status), ("Application version", "1.0.0"), ("Application environment", settings.app_env.title()), ("Workspace mode", "Demonstration" if st.session_state.workspace_mode == "demo" else "Live Gemma"), ("Upload directory", str(settings.upload_dir)), ("Maximum upload", f"{settings.max_upload_mb} MB per file")]
        for label, value in values:
            st.markdown(f"<div class='health-row'><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>", unsafe_allow_html=True)
        st.info("Live mode sends answer page images and the marking scheme to the configured Gemma API. Demo mode never sends pages to a model.")

