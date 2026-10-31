"""Searchable assessment history with review and download actions."""

from __future__ import annotations

import html
from datetime import date

import pandas as pd
import streamlit as st

from components.ui import empty_state, page_header
from database.db import session_scope
from pages._common import rows_for_mode, teacher_id
from services.export_service import class_csv


def render() -> None:
    page_header("Evaluation history", "Find a paper, continue teacher review, or export a class record.", "ASSESSMENT")
    approved_id = st.session_state.pop("evaluation_just_approved", None)
    if approved_id:
        st.success(f"Evaluation #{approved_id} approved. Returned to evaluation history.")
    rows = rows_for_mode()
    if not rows:
        empty_state("No evaluations yet", "Completed evaluations will appear here with their review status and downloadable reports.")
        return
    filters = st.columns([1.2, 1.2, 1.15, 1.15])
    subjects = ["All subjects"] + sorted({r["subject"] for r in rows})
    students = ["All students"] + sorted({r["student"] for r in rows})
    statuses = ["All statuses", "Needs review", "Teacher reviewed", "Approved", "AI suggested"]
    with filters[0]:
        subject = st.selectbox("Subject", subjects)
    with filters[1]:
        student = st.selectbox("Student", students)
    with filters[2]:
        status = st.selectbox("Approval status", statuses)
    with filters[3]:
        query = st.text_input("Search", placeholder="Exam or student")
    dates = st.columns(2)
    min_date = min(r["date"].date() for r in rows)
    max_date = max(r["date"].date() for r in rows)
    with dates[0]:
        start_date = st.date_input("From", value=min_date)
    with dates[1]:
        end_date = st.date_input("To", value=max_date)
    filtered = rows
    if subject != "All subjects": filtered = [r for r in filtered if r["subject"] == subject]
    if student != "All students": filtered = [r for r in filtered if r["student"] == student]
    if status != "All statuses": filtered = [r for r in filtered if r["status"].replace("_", " ").casefold() == status.casefold()]
    if query.strip(): filtered = [r for r in filtered if query.casefold() in f"{r['student']} {r['examination']} {r['subject']}".casefold()]
    filtered = [r for r in filtered if start_date <= r["date"].date() <= end_date] if start_date <= end_date else []
    head = st.columns([5, 1.4])
    with head[0]:
        st.markdown(f"<div class='section-heading compact'><div><h2>{len(filtered)} result(s)</h2><p>Sorted by most recent evaluation</p></div></div>", unsafe_allow_html=True)
    with head[1]:
        with session_scope() as session:
            owner_id = teacher_id(session)
        st.download_button("Export CSV", data=class_csv(filtered, teacher_id=owner_id), file_name="papergrade-evaluations.csv", mime="text/csv", icon=":material/download:", use_container_width=True)
    if not filtered:
        empty_state("No matching evaluations", "Adjust your search or date range to find assessment records.")
        return
    df = pd.DataFrame([{ "Student": r["student"], "Examination": r["examination"], "Subject": r["subject"], "Class": r["class"], "Date": r["date"].strftime("%d %b %Y"), "Score": f"{r['score']:g} / {r['maximum']:g}", "Status": r["status"].replace("_", " ").title()} for r in filtered])
    st.dataframe(df, hide_index=True, use_container_width=True, height=min(450, 38 + 36 * len(df)))
    st.markdown("#### Open an evaluation")
    for row in filtered:
        left, right = st.columns([5, 1.2])
        with left:
            st.markdown(
                f"<div><strong>{html.escape(row['student'])}</strong> · {html.escape(row['examination'])}<br>"
                f"<span class='small-muted'>{html.escape(row['subject'])} · {row['date'].strftime('%d %b %Y')} · {html.escape(row['status'].replace('_', ' ').title())}</span></div>",
                unsafe_allow_html=True,
            )
        with right:
            if st.button("Open review", key=f"history_open_{row['id']}", use_container_width=True):
                st.session_state.selected_evaluation_id = row["id"]
                st.switch_page(st.session_state.page_objects["Evaluation Review"])

