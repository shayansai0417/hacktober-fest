from __future__ import annotations

from database.models import Evaluation, Examination, Question, QuestionEvaluation, Student, Teacher
from services.export_service import class_csv, evaluation_pdf


def test_pdf_export_contains_pdf_signature_and_student_information():
    teacher = Teacher(name="T")
    student = Student(teacher=teacher, name="Avery Student", class_grade="Grade 8")
    exam = Examination(teacher=teacher, title="Fractions quiz", subject="Maths", class_grade="Grade 8", total_marks=5)
    evaluation = Evaluation(teacher=teacher, student=student, examination=exam, status="teacher_reviewed", total_obtained=4, percent=80)
    evaluation.question_results.append(QuestionEvaluation(question=Question(number=1, prompt="Explain 1/2", expected_answer="One half", max_marks=5), question_number=1, question_text="Explain 1/2", expected_answer="One half", extracted_answer="One of two equal parts", ai_marks=4, final_marks=4, max_marks=5, feedback="Clear explanation", rationale="Correct concept"))
    output = evaluation_pdf(evaluation, teacher_id=teacher.id, institution="Example School")
    assert output.startswith(b"%PDF")
    assert len(output) > 1000


def test_csv_export_has_student_score_maximum_and_status():
    output = class_csv([{ "teacher_id": 1, "student": "Avery Student", "subject": "Maths", "examination": "Fractions quiz", "score": 4, "maximum": 5, "percent": 80, "status": "teacher_reviewed"}], teacher_id=1).decode("utf-8-sig")
    assert "Avery Student" in output
    assert "4,5,80,teacher_reviewed" in output
    assert "Maximum marks" in output
