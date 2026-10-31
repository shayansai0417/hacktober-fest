"""Record-backed class performance and difficulty analysis."""

from __future__ import annotations

import html

import plotly.express as px
import streamlit as st

from components.ui import empty_state, page_header
from pages._common import current_mode, rows_for_mode
from services.analytics_service import analytics_payload


def render() -> None:
    demo = current_mode()
    page_header("Class analytics", "Understand progress, assessment coverage, and where learners need support.", "INSIGHTS")
    rows = rows_for_mode()
    mode = "Demo dataset" if demo else "Live records"
    st.caption(f"Showing {mode.lower()} only · {len(rows)} persisted evaluations")
    if not rows:
        empty_state("Build a baseline first", "Question and concept insights appear after enough evaluations have been saved.")
        return
    payload = analytics_payload(rows)
    col_a, col_b = st.columns(2)
    with col_a:
        fig = px.histogram(payload["distribution"], x="Score", nbins=8, color_discrete_sequence=["#A78BFA"])
        fig.update_layout(height=285, margin=dict(l=12, r=8, t=12, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis_title="Score (%)", yaxis_title="Evaluations", bargap=.12, showlegend=False, font_color="#B9B4C0")
        fig.update_traces(marker_line_width=0)
        fig.update_xaxes(range=[0, 100], showgrid=False)
        fig.update_yaxes(gridcolor="#343139")
        st.markdown("<div class='chart-card'><div class='chart-title'>Class performance distribution</div>", unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)
    with col_b:
        fig = px.bar(payload["subject"], x="Subject", y="Average", color_discrete_sequence=["#A78BFA"], text_auto=".0f")
        fig.update_layout(height=285, margin=dict(l=12, r=8, t=12, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis_title="Average score (%)", xaxis_title=None, showlegend=False, font_color="#B9B4C0", yaxis_range=[0, 100], bargap=.45)
        fig.update_traces(textposition="outside")
        fig.update_yaxes(gridcolor="#343139")
        st.markdown("<div class='chart-card'><div class='chart-title'>Average marks by subject</div>", unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)
    col_c, col_d = st.columns(2)
    with col_c:
        fig = px.line(payload["weekly"], x="Week", y="Evaluations", markers=True, color_discrete_sequence=["#A78BFA"])
        fig.update_layout(height=260, margin=dict(l=10, r=8, t=12, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis_title=None, yaxis_title="Evaluations", showlegend=False, font_color="#B9B4C0")
        fig.update_traces(line_width=3, marker_size=8)
        fig.update_yaxes(gridcolor="#343139", rangemode="tozero")
        st.markdown("<div class='chart-card'><div class='chart-title'>Weekly evaluation activity</div>", unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)
    with col_d:
        fig = px.bar(payload["difficulty"], x="Question", y="Average", color_discrete_sequence=["#FBBF24"], text_auto=".0f")
        fig.update_layout(height=260, margin=dict(l=10, r=8, t=12, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis_title=None, yaxis_title="Average marks (%)", yaxis_range=[0, 100], showlegend=False, font_color="#B9B4C0")
        fig.update_traces(textposition="outside")
        fig.update_yaxes(gridcolor="#343139")
        st.markdown("<div class='chart-card'><div class='chart-title'>Question-wise performance</div>", unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("<div class='section-heading'><div><h2>Recorded signals</h2><p>Insights are shown only when the stored sample is large enough.</p></div></div>", unsafe_allow_html=True)
    if payload["insights"]:
        for insight in payload["insights"]:
            st.markdown(f"<div class='insight-card'><span>↗</span>{html.escape(insight)}</div>", unsafe_allow_html=True)
    else:
        st.info("At least three recorded evaluations are needed before this workspace can show class insights.")

