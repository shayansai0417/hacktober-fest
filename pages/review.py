"""Review screen: separate AI suggestions from teacher edits and approval."""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from components.ui import badge, page_header
from database.db import session_scope
from database.models import Evaluation, QuestionEvaluation, TeacherRevision
from pages._common import current_mode, teacher_id
from services.evaluation_service import approve_evaluation, get_evaluation, reopen_evaluation, restore_suggestion, review_overall_feedback, review_question
from services.export_service import evaluation_pdf


def render() -> None:
    evaluation_id = st.session_state.get("selected_evaluation_id")
    if not evaluation_id:
        st.info("Choose an evaluation from Dashboard or Evaluation history.")
        st.page_link(st.session_state.page_objects["Evaluation History"], label="Go to evaluation history", icon=":material/history:")
        return
    with session_scope() as session:
        evaluation = get_evaluation(session, int(evaluation_id), teacher_id(session))
        if evaluation is None or evaluation.is_demo != current_mode():
            evaluation = None
        if evaluation:
            # Detach a compact view before closing the read session.
            report = evaluation_pdf(evaluation, teacher_id=teacher_id(session), institution=evaluation.teacher.institution)
            meta = {"student": evaluation.student.name, "student_code": evaluation.student.student_code or "—", "class": evaluation.student.class_grade or evaluation.examination.class_grade, "exam": evaluation.examination.title, "subject": evaluation.examination.subject, "exam_date": evaluation.examination.exam_date.strftime("%d %b %Y"), "status": evaluation.status, "score": evaluation.total_obtained, "maximum": evaluation.examination.total_marks, "percent": evaluation.percent, "overall": evaluation.overall_feedback, "teacher_feedback": evaluation.teacher_feedback if evaluation.teacher_feedback is not None else evaluation.overall_feedback, "model": evaluation.model_name, "is_demo": evaluation.is_demo, "questions": [{"id": q.id, "number": q.question_number, "prompt": q.question_text, "expected": q.expected_answer, "answer": q.extracted_answer, "ai_marks": q.ai_marks, "marks": q.final_marks, "max": q.max_marks, "ai_feedback": q.ai_feedback, "feedback": q.feedback, "rationale": q.rationale, "correct": q.correct_concepts or [], "missing": q.missing_concepts or [], "incorrect": q.incorrect_statements or [], "confidence": q.confidence, "page": q.page_number, "flag": q.review_flag, "notes": q.private_notes, "overridden": q.overridden} for q in evaluation.question_results], "pages": [p.file_path for p in evaluation.answer_sheet.pages] if evaluation.answer_sheet else []}
    if not evaluation:
        st.error("This evaluation is unavailable in the currently selected workspace.")
        st.page_link(st.session_state.page_objects["Evaluation History"], label="Back to evaluation history")
        return

    page_header(f"{meta['student']} · {meta['exam']}", f"{meta['subject']} · {meta['class']} · Assessment date {meta['exam_date']}", "TEACHER REVIEW")
    toolbar = st.columns([4, 1.3, 1.5])
    with toolbar[0]:
        status_tone = "green" if meta["status"] == "approved" else ("amber" if meta["status"] == "needs_review" else "indigo")
        st.markdown(f"{badge(meta['status'].replace('_', ' ').title(), status_tone)} &nbsp; {badge('DEMO RESULT' if meta['is_demo'] else 'GEMMA RECOMMENDATION', 'amber' if meta['is_demo'] else 'indigo')}", unsafe_allow_html=True)
    with toolbar[1]:
        st.download_button("Download PDF", data=report, file_name=f"papergrade-{meta['student'].replace(' ', '-').lower()}-report.pdf", mime="application/pdf", icon=":material/picture_as_pdf:", use_container_width=True)
    draft_total = sum(float(st.session_state.get(f"review_marks_{q['id']}", q["marks"])) for q in meta["questions"])
    max_total = sum(q["max"] for q in meta["questions"])
    has_unsaved = any(float(st.session_state.get(f"review_marks_{q['id']}", q["marks"])) != q["marks"] or st.session_state.get(f"review_feedback_{q['id']}", q["feedback"]) != q["feedback"] or st.session_state.get(f"review_notes_{q['id']}", q["notes"]) != q["notes"] or st.session_state.get(f"review_flag_{q['id']}", q["flag"]) != q["flag"] for q in meta["questions"])
    has_unsaved = has_unsaved or st.session_state.get(f"review_teacher_feedback_{evaluation_id}", meta["teacher_feedback"]) != meta["teacher_feedback"]
    requires_review = any(st.session_state.get(f"review_flag_{q['id']}", q["flag"]) for q in meta["questions"])
    metric_cols = st.columns([1.2, 1, 1, 1, 2])
    with metric_cols[0]:
        st.markdown(f"<div class='metric-card metric-indigo'><div class='metric-label'>CURRENT SCORE</div><div class='metric-value'>{draft_total:g}<span class='metric-denom'> / {max_total:g}</span></div><div class='metric-note'>Recalculates as marks change</div></div>", unsafe_allow_html=True)
    with metric_cols[1]: st.metric("Percentage", f"{draft_total / max_total * 100:.1f}%" if max_total else "—")
    with metric_cols[2]: st.metric("Questions", len(meta["questions"]))
    with metric_cols[3]: st.metric("Review flags", sum(st.session_state.get(f"review_flag_{q['id']}", q["flag"]) for q in meta["questions"]))
    with metric_cols[4]:
        fig = go.Figure(go.Pie(values=[max(0, draft_total), max(0, max_total - draft_total)], hole=.79, sort=False, direction="clockwise", marker_colors=["#4F46E5", "#EEF2FF"], textinfo="none", hoverinfo="skip"))
        fig.update_layout(height=120, margin=dict(l=0, r=0, t=0, b=0), showlegend=False, paper_bgcolor="rgba(0,0,0,0)", annotations=[dict(text=f"{draft_total / max_total * 100:.0f}%" if max_total else "—", x=.5, y=.52, font=dict(size=20, color="#172033", family="Inter"), showarrow=False)])
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown("<div class='review-key'><span>AI SUGGESTED</span><i></i><span>TEACHER REVIEWED</span><i></i><span>TEACHER APPROVED</span></div>", unsafe_allow_html=True)
    if meta["is_demo"]:
        st.info("DEMO RESULT · This deterministic sample was not produced by Gemma and does not represent analysis of handwriting.")
    if meta["pages"]:
        with st.expander("Original uploaded answer sheet", expanded=False):
            for index, path in enumerate(meta["pages"], 1):
                try:
                    st.image(Path(path).read_bytes(), caption=f"Page {index} · full page view; no answer-region crop was detected.", use_container_width=True)
                except OSError:
                    st.warning(f"Page {index} is not available from the configured persistent storage path.")
    st.markdown("<div class='section-heading'><div><h2>Question-by-question review</h2><p>Adjust recommended marks and feedback. Original AI suggestions remain recorded.</p></div></div>", unsafe_allow_html=True)
    for q in meta["questions"]:
        with st.expander(f"Question {q['number']}  ·  {q['marks']:g} / {q['max']:g} suggested", expanded=q["flag"]):
            st.markdown(f"**Question**  \n{q['prompt']}")
            answer = q["answer"] or "No answer detected."
            st.markdown(f"**Handwritten answer read**  \n{answer}")
            st.markdown(f"**Expected answer**  \n{q['expected'] or '—'}")
            st.markdown(f"**Evaluation explanation**  \n{q['rationale'] or '—'}")
            lcol, rcol = st.columns(2)
            with lcol:
                st.markdown("**Concepts identified**")
                st.write(", ".join(q["correct"]) or "None identified")
                st.markdown("**Concepts missing**")
                st.write(", ".join(q["missing"]) or "None")
            with rcol:
                st.markdown("**Incorrect statements**")
                st.write(", ".join(q["incorrect"]) or "None identified")
                st.markdown(f"**Readability confidence**  \n{q['confidence']:.0%} · Page {q['page'] or 'not mapped'}")
            current_marks = float(st.session_state.get(f"review_marks_{q['id']}", q["marks"]))
            mark = st.number_input("Teacher-approved marks", min_value=0.0, max_value=float(q["max"]), value=min(float(q["max"]), current_marks), step=0.25, key=f"review_marks_{q['id']}")
            feedback = st.text_area("Feedback for student", value=q["feedback"], key=f"review_feedback_{q['id']}")
            notes = st.text_area("Private teacher notes", value=q["notes"], key=f"review_notes_{q['id']}")
            flagged = st.checkbox("Keep flagged for teacher review", value=q["flag"], key=f"review_flag_{q['id']}")
            buttons = st.columns([1.4, 1.5, 3])
            with buttons[0]:
                if st.button("Save changes", key=f"save_question_{q['id']}", type="primary", use_container_width=True):
                    _save_question(int(evaluation_id), q["id"], mark, feedback, notes, flagged)
            with buttons[1]:
                if st.button("Restore AI suggestion", key=f"restore_question_{q['id']}", use_container_width=True):
                    _restore_question(int(evaluation_id), q["id"])
            with buttons[2]:
                if q["overridden"]:
                    st.caption(f"AI suggested {q['ai_marks']:g} / {q['max']:g} · Teacher set {q['marks']:g} / {q['max']:g}")
                else:
                    st.caption(f"AI suggested {q['ai_marks']:g} / {q['max']:g} · Not yet overridden")
    with session_scope() as session:
        current = session.scalar(select(Evaluation).where(Evaluation.id == int(evaluation_id), Evaluation.teacher_id == teacher_id(session)))
        is_approved = bool(current and current.status == "approved")
    st.markdown("#### Overall feedback for the student")
    st.caption("The AI suggestion is kept separately. Edit the student-facing feedback here; save it before final approval.")
    if meta["overall"]:
        with st.expander("View original AI feedback suggestion", expanded=False):
            st.write(meta["overall"])
    teacher_feedback = st.text_area(
        "Teacher feedback",
        value=meta["teacher_feedback"],
        key=f"review_teacher_feedback_{evaluation_id}",
        height=130,
        disabled=is_approved,
    )
    if not is_approved:
        if st.button("Save teacher feedback", key=f"save_teacher_feedback_{evaluation_id}", icon=":material/save:", disabled=teacher_feedback == meta["teacher_feedback"]):
            _save_overall_feedback(int(evaluation_id), teacher_feedback)
    st.markdown("<div class='approval-panel'><div><strong>Final teacher approval</strong><span>The record is approved only after you confirm every flagged answer and save any score changes.</span></div></div>", unsafe_allow_html=True)
    if is_approved:
        st.success(f"Approved by teacher on {current.approved_at.strftime('%d %b %Y, %H:%M') if current and current.approved_at else 'recorded date'}.")
        if st.button("Reopen for review", icon=":material/edit:"):
            _reopen(int(evaluation_id))
    else:
        if has_unsaved:
            st.warning("Save your score, question feedback, and overall teacher feedback changes before approval.")
        if requires_review:
            st.warning("Clear each teacher-review flag after resolving or confirming that question.")
        if st.button("Approve final evaluation", icon=":material/verified:", type="primary", disabled=has_unsaved or requires_review):
            _approve(int(evaluation_id))


def _save_question(evaluation_id: int, question_eval_id: int, marks: float, feedback: str, notes: str, flagged: bool) -> None:
    with session_scope() as session:
        evaluation = get_evaluation(session, evaluation_id, teacher_id(session))
        if not evaluation: st.error("Evaluation not found."); return
        result = next((r for r in evaluation.question_results if r.id == question_eval_id), None)
        if not result: st.error("Question result not found."); return
        review_question(session, evaluation, result, marks, feedback, notes, teacher_id=teacher_id(session))
        if result.review_flag != flagged:
            session.add(TeacherRevision(evaluation_id=evaluation.id, question_number=result.question_number, field_name="review_flag", previous_value=str(result.review_flag), new_value=str(flagged)))
            result.review_flag = flagged
        st.success("Teacher changes saved. The total score was recalculated.")
    st.rerun()


def _restore_question(evaluation_id: int, question_eval_id: int) -> None:
    with session_scope() as session:
        evaluation = get_evaluation(session, evaluation_id, teacher_id(session))
        if evaluation:
            result = next((r for r in evaluation.question_results if r.id == question_eval_id), None)
            if result: restore_suggestion(session, evaluation, result, teacher_id=teacher_id(session))
    for key in (f"review_marks_{question_eval_id}", f"review_feedback_{question_eval_id}", f"review_notes_{question_eval_id}", f"review_flag_{question_eval_id}"):
        st.session_state.pop(key, None)
    st.rerun()


def _save_overall_feedback(evaluation_id: int, feedback: str) -> None:
    with session_scope() as session:
        evaluation = get_evaluation(session, evaluation_id, teacher_id(session))
        if not evaluation:
            st.error("Evaluation not found.")
            return
        try:
            review_overall_feedback(session, evaluation, feedback, teacher_id=teacher_id(session))
        except ValueError as exc:
            st.error(str(exc))
            return
    st.rerun()


def _approve(evaluation_id: int) -> None:
    approved = False
    with session_scope() as session:
        evaluation = get_evaluation(session, evaluation_id, teacher_id(session))
        if evaluation:
            try:
                approve_evaluation(session, evaluation, teacher_id=teacher_id(session))
                approved = True
            except ValueError as exc:
                st.error(str(exc))
                return
    if approved:
        st.session_state["evaluation_just_approved"] = evaluation_id
        st.session_state.pop("selected_evaluation_id", None)
        st.switch_page(st.session_state.page_objects["Evaluation History"])


def _reopen(evaluation_id: int) -> None:
    with session_scope() as session:
        evaluation = get_evaluation(session, evaluation_id, teacher_id(session))
        if evaluation:
            reopen_evaluation(session, evaluation, teacher_id=teacher_id(session))
    st.rerun()

