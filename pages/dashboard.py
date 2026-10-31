"""Teacher overview with persisted counts, trends, and recent work."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func, select

from components.ui import empty_state, page_header
from database.db import session_scope
from database.models import Evaluation, Student
from pages._common import current_mode, rows_for_mode, teacher_id
from services.analytics_service import analytics_payload


def render() -> None:
    demo = current_mode()
    page_header(f"Good morning, {st.session_state.get('auth_teacher_name', 'Teacher')}.", "Here’s your assessment overview.", "OVERVIEW")
    action = st.columns([5, 1.5])
    with action[1]:
        st.page_link(st.session_state.page_objects["New Evaluation"], label="New evaluation", icon=":material/add:", use_container_width=True)
    rows = rows_for_mode()
    if demo:
        demo_note = "Sample records stay labeled. New grading uses Gemma when configured; otherwise it uses a repeatable sample result."
        st.markdown(f"<div class='mode-banner'><span class='demo-dot'></span><div><strong>Demonstration workspace</strong><span>{demo_note}</span></div></div>", unsafe_allow_html=True)
    elif not st.session_state.get("gemma_ready"):
        st.warning("Live Gemma mode is selected, but GEMMA_API_KEY is not configured. Add it to your environment to grade answer sheets.")

    with session_scope() as session:
        t_id = teacher_id(session)
        evals = session.scalars(select(Evaluation).where(Evaluation.teacher_id == t_id, Evaluation.is_demo.is_(demo))).all()
        avg = round(sum(e.percent for e in evals) / len(evals), 1) if evals else 0
        pending = sum(e.status != "approved" for e in evals)
        processed = len(evals)
        student_count = session.scalar(select(func.count()).select_from(Student).where(Student.teacher_id == t_id, Student.is_demo.is_(demo))) or 0
        # Activity savings use a conservative, visible estimate and are derived from stored sheets.
        time_saved = round(len(evals) * 8.5, 1)
    cards = st.columns(5)
    metrics = [("Evaluations completed", processed, "Across your assessments", "indigo"), ("Awaiting review", pending, "Teacher approval stays in control", "amber"), ("Class average", f"{avg:.1f}%" if evals else "—", "Based on stored evaluations", "green"), ("Students", student_count, "In this teacher workspace", "blue"), ("Time returned", f"{time_saved:.1f}h" if evals else "—", "Estimate · 8.5 min per paper", "blue")]
    for col, (label, value, note, tone) in zip(cards, metrics):
        with col:
            st.markdown(f"<div class='metric-card metric-{tone}'><div class='metric-label'>{label}</div><div class='metric-value'>{value}</div><div class='metric-note'>{note}</div></div>", unsafe_allow_html=True)
    st.markdown("<div class='section-heading'><div><h2>Performance snapshot</h2><p>Scores and volume from the selected workspace</p></div></div>", unsafe_allow_html=True)
    if not rows:
        empty_state("Your assessment workspace is ready", "Start an evaluation or load the demonstration dataset to see class performance here.")
        return
    left, right = st.columns([1.5, 1])
    with left:
        f = pd.DataFrame(rows)
        subject = f.groupby("subject", as_index=False)["percent"].mean().rename(columns={"subject": "Subject", "percent": "Average score"})
        fig = px.bar(subject, x="Subject", y="Average score", color_discrete_sequence=["#A78BFA"], text_auto=".0f")
        fig.update_layout(height=270, margin=dict(l=10, r=10, t=18, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#B9B4C0", yaxis_range=[0, 100], yaxis_title="Average score (%)", xaxis_title=None, showlegend=False, bargap=.48)
        fig.update_traces(marker_line_width=0, textposition="outside", textfont_color="#EAE6EF")
        fig.update_yaxes(showgrid=True, gridcolor="#343139", zeroline=False)
        fig.update_xaxes(showgrid=False, linecolor="#45424A")
        st.markdown("<div class='chart-card'><div class='chart-title'>Average score by subject</div>", unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        scores = pd.DataFrame({"Score band": ["Below 60%", "60–79%", "80% and above"], "Students": [sum(r["percent"] < 60 for r in rows), sum(60 <= r["percent"] < 80 for r in rows), sum(r["percent"] >= 80 for r in rows)]})
        fig = px.pie(scores, names="Score band", values="Students", hole=.72, color="Score band", color_discrete_map={"Below 60%": "#FBBF24", "60–79%": "#A78BFA", "80% and above": "#34D399"})
        fig.update_layout(height=270, margin=dict(l=0, r=0, t=14, b=2), paper_bgcolor="rgba(0,0,0,0)", showlegend=True, legend=dict(orientation="h", y=-.12, x=0, font=dict(size=10, color="#B9B4C0")), font_color="#B9B4C0")
        fig.update_traces(textinfo="none", marker_line=dict(color="#171719", width=3))
        st.markdown("<div class='chart-card'><div class='chart-title'>Score distribution</div>", unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)
    weekly = analytics_payload(rows)["weekly"]
    if not weekly.empty:
        st.markdown("<div class='section-heading'><div><h2>Weekly activity</h2><p>Evaluations saved in your workspace over recent weeks</p></div></div>", unsafe_allow_html=True)
        fig = px.bar(weekly, x="Week", y="Evaluations", color_discrete_sequence=["#A78BFA"], text_auto=True)
        fig.update_layout(height=210, margin=dict(l=10, r=10, t=10, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis_title=None, yaxis_title="Evaluations", showlegend=False, font_color="#B9B4C0")
        fig.update_yaxes(gridcolor="#343139", rangemode="tozero")
        fig.update_xaxes(showgrid=False, linecolor="#45424A")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown("<div class='section-heading'><div><h2>Recent evaluations</h2><p>The latest answer sheets in this workspace</p></div></div>", unsafe_allow_html=True)
    display = pd.DataFrame([{ "Student": r["student"], "Examination": r["examination"], "Subject": r["subject"], "Score": f"{r['score']:g} / {r['maximum']:g}", "Date": r["date"].strftime("%d %b %Y"), "Status": r["status"].replace("_", " ").title()} for r in rows[:6]])
    st.dataframe(display, hide_index=True, use_container_width=True, height=min(310, 38 + 36 * len(display)))
    open_cols = st.columns(min(6, len(rows)))
    for col, row in zip(open_cols, rows[:6]):
        with col:
            if st.button(f"Review · {row['student'].split()[0]}", key=f"dashboard_review_{row['id']}", use_container_width=True):
                st.session_state.selected_evaluation_id = row["id"]
                st.switch_page(st.session_state.page_objects["Evaluation Review"])

