"""Student management with duplicate identifiers and history safeguards."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from components.ui import empty_state, page_header
from database.db import session_scope
from database.models import Evaluation, Student, Teacher
from pages._common import current_mode, teacher_id
from services.student_service import create_student, delete_student, update_student


def render() -> None:
    demo = current_mode()
    page_header("Students", "Manage class records and see each learner’s assessment history.", "MANAGEMENT")
    left, right = st.columns([1.3, 2.3])
    with left:
        st.markdown("<div class='section-heading compact'><div><h2>Add student</h2><p>Student IDs are unique within this teacher workspace</p></div></div>", unsafe_allow_html=True)
        with st.form("add_student"):
            name = st.text_input("Student name")
            code = st.text_input("Student ID (optional)")
            class_name = st.text_input("Class / grade")
            email = st.text_input("Email (optional)")
            save = st.form_submit_button("Add student", type="primary", use_container_width=True)
        if save:
            if not name.strip() or not class_name.strip():
                st.error("Student name and class are required.")
            else:
                try:
                    with session_scope() as session:
                        create_student(session, teacher_id=teacher_id(session), name=name, student_code=code, class_grade=class_name, email=email, is_demo=demo)
                    st.success("Student added.")
                    st.rerun()
                except ValueError as exc: st.error(str(exc))
                except IntegrityError: st.error("That student ID already exists in this teacher workspace.")
    with session_scope() as session:
        tid = teacher_id(session)
        students = session.scalars(select(Student).where(Student.teacher_id == tid, Student.is_demo.is_(demo)).options(selectinload(Student.evaluations)).order_by(Student.name)).all()
        records = [{"id": s.id, "name": s.name, "code": s.student_code or "—", "class": s.class_grade, "email": s.email, "count": sum(1 for e in s.evaluations if e.is_demo == demo), "average": round(sum(e.percent for e in s.evaluations if e.is_demo == demo) / max(1, sum(1 for e in s.evaluations if e.is_demo == demo)), 1) if any(e.is_demo == demo for e in s.evaluations) else None} for s in students]
    with right:
        top = st.columns([2, 1])
        with top[0]: search = st.text_input("Search students", placeholder="Name or student ID")
        with top[1]: grade = st.selectbox("Class", ["All classes"] + sorted({r["class"] for r in records if r["class"]}))
        display = [r for r in records if (not search.strip() or search.casefold() in f"{r['name']} {r['code']}".casefold()) and (grade == "All classes" or r["class"] == grade)]
        if display:
            st.dataframe(pd.DataFrame([{ "Student": r["name"], "Student ID": r["code"], "Class": r["class"], "Assessments": r["count"], "Average": f"{r['average']:.1f}%" if r["average"] is not None else "—"} for r in display]), hide_index=True, use_container_width=True, height=min(360, 38 + 36 * len(display)))
        elif not records:
            empty_state("No students yet", "Add a learner to create their assessment profile.")
        else:
            empty_state("No matching students", "Try another name or class filter.")
    if not records:
        return
    st.markdown("<div class='section-heading'><div><h2>Student profile</h2><p>Assessment results and performance over time</p></div></div>", unsafe_allow_html=True)
    options = {f"{r['name']} · {r['code']} · {r['class']}": r for r in records}
    label = st.selectbox("Open profile", list(options))
    selected = options[label]
    with session_scope() as session:
        student = session.scalar(select(Student).where(Student.id == selected["id"], Student.teacher_id == teacher_id(session)).options(selectinload(Student.evaluations).selectinload(Evaluation.examination)))
        evaluations = [e for e in student.evaluations if e.is_demo == demo] if student else []
    profile = st.columns(4)
    avg = sum(e.percent for e in evaluations) / len(evaluations) if evaluations else None
    for col, title, val in zip(profile, ["Class", "Student ID", "Average mark", "Evaluations"], [selected["class"], selected["code"], f"{avg:.1f}%" if avg is not None else "—", str(len(evaluations))]):
        with col: st.metric(title, val)
    if evaluations:
        chart = pd.DataFrame([{ "Assessment": e.examination.title, "Score": e.percent, "Date": e.evaluated_at} for e in sorted(evaluations, key=lambda e: e.evaluated_at)])
        fig = px.line(chart, x="Date", y="Score", markers=True, color_discrete_sequence=["#4F46E5"], hover_name="Assessment")
        fig.update_layout(height=250, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis_title="Score (%)", xaxis_title=None, showlegend=False, yaxis_range=[0, 100], font_color="#64748B")
        fig.update_yaxes(gridcolor="#EDF0F5")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.dataframe(pd.DataFrame([{ "Assessment": e.examination.title, "Subject": e.examination.subject, "Score": f"{e.total_obtained:g} / {e.examination.total_marks:g}", "Status": e.status.replace("_", " ").title()} for e in sorted(evaluations, key=lambda e: e.evaluated_at, reverse=True)]), hide_index=True, use_container_width=True)
    edit = st.expander("Edit or remove selected student")
    with edit:
        with st.form(f"edit_student_{selected['id']}"):
            edit_name = st.text_input("Name", value=selected["name"])
            edit_code = st.text_input("Student ID", value="" if selected["code"] == "—" else selected["code"])
            edit_class = st.text_input("Class / grade", value=selected["class"])
            edit_email = st.text_input("Email", value=selected["email"])
            save_edit = st.form_submit_button("Save profile changes", type="primary")
        if save_edit:
            try:
                with session_scope() as session:
                    update_student(session, selected["id"], teacher_id=teacher_id(session), name=edit_name, student_code=edit_code, class_grade=edit_class, email=edit_email)
                st.success("Student profile updated.")
                st.rerun()
            except ValueError as exc: st.error(str(exc))
        if evaluations:
            st.caption("This learner has saved evaluations, so the student record cannot be deleted without damaging assessment history.")
        else:
            confirm = st.checkbox("I understand this student profile will be removed.", key=f"confirm_delete_{selected['id']}")
            if st.button("Delete student", key=f"delete_student_{selected['id']}", disabled=not confirm):
                try:
                    with session_scope() as session:
                        delete_student(session, selected["id"], teacher_id=teacher_id(session))
                except (PermissionError, ValueError) as exc:
                    st.error(str(exc))
                    return
                st.rerun()

