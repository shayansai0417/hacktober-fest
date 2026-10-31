"""Idempotent demo dataset for first-run exploration without an API key."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import ROOT_DIR, settings
from database.models import AnswerSheet, Evaluation, Examination, Question, QuestionEvaluation, Student, Teacher, UploadedPage
from schemas import EvaluationResult, MarkingScheme, QuestionEvaluationOut
from services.auth_service import ensure_demo_account


SAMPLE_SHEET = ROOT_DIR / "sample_data" / "demo_answer_sheet.png"


def create_handwritten_sample() -> Path:
    if SAMPLE_SHEET.exists():
        return SAMPLE_SHEET
    SAMPLE_SHEET.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1100, 1500), "#fffefb")
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype(r"C:\Windows\Fonts\Inkfree.ttf", 38)
        hand_font = ImageFont.truetype(r"C:\Windows\Fonts\Inkfree.ttf", 34)
    except OSError:
        candidates = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"]
        font_path = next((p for p in candidates if Path(p).exists()), None)
        title_font = ImageFont.truetype(font_path, 34) if font_path else ImageFont.load_default()
        hand_font = ImageFont.truetype(font_path, 31) if font_path else ImageFont.load_default()
    # Thin blue ruling and a red margin emulate a student's exercise-book page.
    for y in range(190, 1450, 62):
        draw.line((70, y, 1040, y), fill="#d9e6f3", width=2)
    draw.line((156, 70, 156, 1450), fill="#e9b8b8", width=2)
    draw.text((195, 68), "Northstar Learning Centre  ·  Mathematics", font=title_font, fill="#253c5b")
    draw.text((195, 124), "Name: Leena Rao          Algebra Checkpoint", font=hand_font, fill="#253c5b")
    lines = [
        "1)  3x + 5 = 20",
        "     take 5 away from both sides",
        "     3x = 15",
        "     x = 15 / 3 = 5",
        "",
        "2)  Area = length x width",
        "     8 x 4 = 32 cm",
        "     (I need to remember square units!)",
        "",
        "3)  3/5 = 6/10 = .6",
        "     so they show the same amount",
    ]
    y = 214
    for index, line in enumerate(lines):
        draw.text((190, y), line, font=hand_font, fill="#273d62")
        if index in (1, 6, 9):
            # Small natural baselines variation, kept within readable limits.
            y += 64
        y += 61
    image.save(SAMPLE_SHEET, optimize=True)
    return SAMPLE_SHEET


def _q(number: int, prompt: str, answer: str, marks: float, concepts: list[str]) -> Question:
    return Question(number=number, prompt=prompt, expected_answer=answer, max_marks=marks, key_concepts=concepts, alternatives=[], criteria=[])


def seed_demo(session: Session) -> None:
    teacher = ensure_demo_account(session)
    if teacher is None:
        return
    sheet = create_handwritten_sample()
    if session.scalar(select(Student.id).where(Student.teacher_id == teacher.id, Student.is_demo.is_(True))) is not None:
        return

    people = [("Leena Rao", "PG-024", "Grade 8"), ("Aaron Chen", "PG-031", "Grade 8"), ("Isha Mehta", "PG-018", "Grade 8"), ("Mateo Silva", "PG-042", "Grade 8")]
    students = [Student(teacher_id=teacher.id, name=name, student_code=code, class_grade=grade, is_demo=True) for name, code, grade in people]
    session.add_all(students)
    session.flush()
    schemes = [
        ("Algebra Checkpoint", "Mathematics", [_q(1, "Solve 3x + 5 = 20. Show your working.", "x = 5", 5, ["inverse operations", "x = 5"]), _q(2, "Find the area of an 8 cm by 4 cm rectangle.", "32 cm²", 5, ["area formula", "square units"]), _q(3, "Explain why 0.6 = 3/5.", "3/5 = 6/10 = 0.6", 5, ["equivalent fraction", "decimal"])]),
        ("Forces & Motion", "Science", [_q(1, "Define friction and give one effect.", "A force opposing motion between surfaces.", 5, ["opposes motion", "surfaces"]), _q(2, "How does a balanced force affect motion?", "No change in velocity.", 5, ["net force zero", "constant velocity"]), _q(3, "Name the SI unit of force.", "Newton (N)", 5, ["newton", "N"])]),
        ("Matter in Motion", "Science", [_q(1, "Describe how particles are arranged in a solid.", "Closely packed in fixed positions.", 5, ["close together", "fixed positions"]), _q(2, "What happens to particles when a liquid is heated?", "They gain kinetic energy and move faster.", 5, ["gain energy", "move faster"]), _q(3, "Explain condensation.", "Gas changes to liquid when it loses heat.", 5, ["gas to liquid", "cooling"])]),
    ]
    exams = []
    today = date.today()
    for offset, (title, subject, questions) in enumerate(schemes):
        exam = Examination(teacher_id=teacher.id, title=title, subject=subject, class_grade="Grade 8", academic_year=f"{today.year}-{today.year + 1}", exam_date=today - timedelta(days=offset * 10 + 2), total_marks=15, is_demo=True, questions=questions)
        session.add(exam)
        exams.append(exam)
    session.flush()

    scores = [[5, 3, 5], [4, 4, 3], [3, 4, 4], [5, 5, 2], [4, 3, 3], [4, 4, 5], [3, 4, 2], [5, 3, 4], [4, 5, 3], [5, 4, 4], [3, 3, 5], [4, 4, 4]]
    comments = ["Clear method and confident working.", "Good progress; check how you present units.", "A solid attempt. Revisit the key vocabulary.", "Strong understanding with one detail to refine."]
    all_results: list[Evaluation] = []
    cursor = 0
    for exam_idx, exam in enumerate(exams):
        for student_idx, student in enumerate(students):
            marks = scores[cursor]
            cursor += 1
            eval_date = today - timedelta(days=exam_idx * 10 + student_idx + 2)
            eval_datetime = __import__("datetime").datetime.combine(eval_date, __import__("datetime").time(10, 0), tzinfo=__import__("datetime").timezone.utc)
            status = "approved" if cursor % 3 == 0 else ("teacher_reviewed" if cursor % 3 == 1 else "needs_review")
            evaluation = Evaluation(teacher_id=teacher.id, student=student, examination=exam, is_demo=True, status=status, approved_at=eval_datetime if status == "approved" else None, total_obtained=sum(marks), percent=round(sum(marks) / 15 * 100, 1), overall_feedback=comments[student_idx], model_name="DEMO · deterministic sample", evaluated_at=eval_datetime, ai_confidence=0.93)
            for q, score in zip(exam.questions, marks):
                evaluation.question_results.append(QuestionEvaluation(question=q, question_number=q.number, question_text=q.prompt, expected_answer=q.expected_answer, extracted_answer=q.expected_answer if score >= 4 else "Partly correct explanation with one missed step.", ai_marks=score, final_marks=score, max_marks=q.max_marks, ai_feedback=comments[student_idx], feedback=comments[student_idx], rationale=f"Sample criterion: {q.key_concepts[0]}", correct_concepts=q.key_concepts[:1] if score >= 4 else [], missing_concepts=[] if score >= 4 else q.key_concepts[-1:], confidence=0.93 if score >= 4 else 0.77, page_number=1, review_flag=(cursor % 3 == 2)))
            if cursor == 1:
                evaluation.status = "teacher_reviewed"
                sheet_blob = sheet.read_bytes()
                answer_sheet = AnswerSheet(original_name="leena-algebra-answer-sheet.png")
                answer_sheet.pages.append(UploadedPage(page_number=1, file_path=str(sheet), mime_type="image/png", sha256=__import__("hashlib").sha256(sheet_blob).hexdigest(), size_bytes=len(sheet_blob)))
                evaluation.answer_sheet = answer_sheet
            session.add(evaluation)
            all_results.append(evaluation)

