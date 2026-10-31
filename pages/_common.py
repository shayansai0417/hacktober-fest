"""Shared page helpers and read-only repository access."""

from __future__ import annotations

from sqlalchemy import select

from database.db import session_scope
from database.models import Evaluation, Student, Teacher
from services.analytics_service import evaluation_rows


def teacher_id(session) -> int:
    """Return the owner from the validated server-side Streamlit session."""
    import streamlit as st
    owner_id = st.session_state.get("auth_teacher_id")
    if not owner_id:
        raise PermissionError("Sign in before accessing teacher records.")
    teacher = session.scalar(select(Teacher.id).where(Teacher.id == owner_id))
    if teacher is None:
        raise PermissionError("The signed-in teacher workspace is no longer available.")
    return teacher


def current_mode() -> bool:
    import streamlit as st
    return st.session_state.get("workspace_mode", "demo") == "demo"


def rows_for_mode() -> list[dict]:
    with session_scope() as session:
        return evaluation_rows(session, teacher_id(session), current_mode())


def students_for_mode() -> list[Student]:
    with session_scope() as session:
        rows = session.scalars(select(Student).where(Student.teacher_id == teacher_id(session), Student.is_demo.is_(current_mode())).order_by(Student.name)).all()
        return [{"id": r.id, "name": r.name, "code": r.student_code or "—", "class": r.class_grade or "—"} for r in rows]


def evaluation_for_mode(evaluation_id: int) -> dict | None:
    with session_scope() as session:
        row = session.scalar(select(Evaluation).where(Evaluation.id == evaluation_id, Evaluation.teacher_id == teacher_id(session)))
        if row is None or row.is_demo != current_mode():
            return None
        return {"id": row.id, "status": row.status, "student": row.student.name, "exam": row.examination.title, "subject": row.examination.subject}

