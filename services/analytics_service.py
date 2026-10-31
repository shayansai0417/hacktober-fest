"""Aggregate only persisted records; demo and live workspaces stay separate."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from database.models import Evaluation, QuestionEvaluation


def evaluation_rows(session: Session, teacher_id: int, is_demo: bool) -> list[dict]:
    records = session.scalars(select(Evaluation).where(Evaluation.teacher_id == teacher_id, Evaluation.is_demo == is_demo).options(
        selectinload(Evaluation.student), selectinload(Evaluation.examination), selectinload(Evaluation.question_results)
    ).order_by(Evaluation.evaluated_at.desc())).all()
    return [{"id": r.id, "teacher_id": r.teacher_id, "student": r.student.name, "student_id": r.student_id, "class": r.student.class_grade or r.examination.class_grade,
             "examination": r.examination.title, "subject": r.examination.subject, "date": r.evaluated_at,
             "score": r.total_obtained, "maximum": r.examination.total_marks, "percent": r.percent,
             "status": r.status, "questions": r.question_results, "overall_feedback": r.overall_feedback} for r in records]


def analytics_payload(rows: list[dict]) -> dict:
    if not rows:
        return {"subject": pd.DataFrame(columns=["Subject", "Average"]), "weekly": pd.DataFrame(columns=["Week", "Evaluations"]), "distribution": pd.DataFrame(columns=["Student", "Score"]), "difficulty": pd.DataFrame(columns=["Question", "Average"]), "insights": []}
    frame = pd.DataFrame(rows)
    subject = frame.groupby("subject", as_index=False)["percent"].mean().rename(columns={"subject": "Subject", "percent": "Average"})
    frame["week"] = pd.to_datetime(frame["date"]).dt.to_period("W").astype(str)
    weekly = frame.groupby("week", as_index=False).size().rename(columns={"week": "Week", "size": "Evaluations"}).tail(8)
    distribution = frame[["student", "percent"]].rename(columns={"student": "Student", "percent": "Score"})
    q_rows = []
    concept_misses: dict[str, int] = defaultdict(int)
    for row in rows:
        for q in row["questions"]:
            q_rows.append({"Question": f"Q{q.question_number}", "percent": q.final_marks / q.max_marks * 100 if q.max_marks else 0})
            for concept in q.missing_concepts or []:
                concept_misses[concept] += 1
    q_frame = pd.DataFrame(q_rows)
    difficulty = q_frame.groupby("Question", as_index=False)["percent"].mean().rename(columns={"percent": "Average"}) if not q_frame.empty else pd.DataFrame(columns=["Question", "Average"])
    insights = []
    if len(rows) >= 3 and not subject.empty:
        low = subject.sort_values("Average").iloc[0]
        insights.append(f"{low['Subject']} has the lowest average at {low['Average']:.0f}% across {len(rows)} evaluations.")
    if len(rows) >= 3 and not difficulty.empty:
        lowq = difficulty.sort_values("Average").iloc[0]
        insights.append(f"{lowq['Question']} is currently the most challenging, averaging {lowq['Average']:.0f}%.")
    if len(rows) >= 3 and concept_misses:
        concept, count = max(concept_misses.items(), key=lambda item: item[1])
        insights.append(f"“{concept}” was marked missing {count} times in recorded responses.")
    return {"subject": subject, "weekly": weekly, "distribution": distribution, "difficulty": difficulty, "insights": insights}

