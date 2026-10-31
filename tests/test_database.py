from __future__ import annotations

from sqlalchemy import select

from database.models import Evaluation, QuestionEvaluation, Student, TeacherRevision
from services.evaluation_service import approve_evaluation, get_evaluation, review_question
from schemas import EvaluationResult, QuestionEvaluationOut
from services.evaluation_service import save_evaluation
from config import settings


def _make_evaluation(session, page_data=None):
    teacher = session.scalar(select(__import__("database.models", fromlist=["Teacher"]).Teacher))
    student = session.scalar(select(Student))
    exam = session.scalar(select(__import__("database.models", fromlist=["Examination"]).Examination))
    result = EvaluationResult(student_name=student.name, question_evaluations=[
        QuestionEvaluationOut(question_number=1, extracted_answer="4", suggested_marks=5, feedback="Correct", confidence=.9, readability="clear"),
        QuestionEvaluationOut(question_number=2, extracted_answer="6", suggested_marks=3, feedback="Check addition", confidence=.8, readability="clear"),
    ], overall_feedback="Good work")
    return save_evaluation(session, teacher.id, student, exam, __import__("schemas").MarkingScheme.model_validate({"questions":[{"number":1,"prompt":"Solve 2 + 2","expected_answer":"4","max_marks":5,"key_concepts":["addition"]},{"number":2,"prompt":"Solve 3 + 4","expected_answer":"7","max_marks":5,"key_concepts":["addition"]}]}), result, page_data or [], False, "test-model")


def test_create_persist_and_retrieve_evaluation(db_session):
    evaluation = _make_evaluation(db_session)
    db_session.commit()
    evaluation_id = evaluation.id
    db_session.expire_all()
    fetched = get_evaluation(db_session, evaluation_id, evaluation.teacher_id)
    assert fetched is not None
    assert fetched.student.name == "Avery Student"
    assert fetched.examination.title == "Unit Check"
    assert fetched.total_obtained == 8
    assert len(fetched.question_results) == 2


def test_edit_evaluation_records_revision_and_recalculates_score(db_session):
    evaluation = _make_evaluation(db_session)
    result = evaluation.question_results[1]
    original_suggestion = result.ai_marks
    review_question(db_session, evaluation, result, 4, "Correct approach, small slip.", "Reviewed working", teacher_id=evaluation.teacher_id)
    db_session.commit()
    assert evaluation.total_obtained == 9
    assert result.ai_marks == original_suggestion == 3
    assert result.final_marks == 4
    assert db_session.scalar(select(TeacherRevision).where(TeacherRevision.field_name == "final_marks")) is not None


def test_approve_persists_explicit_approval(db_session):
    evaluation = _make_evaluation(db_session)
    approve_evaluation(db_session, evaluation, teacher_id=evaluation.teacher_id)
    db_session.commit()
    assert evaluation.status == "approved"
    assert evaluation.approved_at is not None
    assert db_session.scalar(select(Evaluation).where(Evaluation.id == evaluation.id)).status == "approved"


def test_approval_is_blocked_while_question_needs_review(db_session):
    evaluation = _make_evaluation(db_session)
    evaluation.question_results[0].review_flag = True
    try:
        approve_evaluation(db_session, evaluation, teacher_id=evaluation.teacher_id)
    except ValueError as exc:
        assert "Resolve every teacher review flag" in str(exc)
    else:
        raise AssertionError("Approval should require all review flags to be resolved")


def test_uploaded_files_persist_on_commit_and_are_removed_on_rollback(db_session, tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    committed = _make_evaluation(db_session, [("page.jpg", b"committed-jpeg-bytes")])
    committed_path = Path(committed.answer_sheet.pages[0].file_path)
    db_session.commit()
    assert committed_path.read_bytes() == b"committed-jpeg-bytes"

    pending = _make_evaluation(db_session, [("page.jpg", b"uncommitted-jpeg-bytes")])
    pending_path = Path(pending.answer_sheet.pages[0].file_path)
    assert pending_path.exists()
    db_session.rollback()
    assert committed_path.exists()
    assert not pending_path.exists()


def test_approval_is_blocked_while_question_needs_review(db_session):
    evaluation = _make_evaluation(db_session)
    evaluation.question_results[0].review_flag = True
    try:
        approve_evaluation(db_session, evaluation, teacher_id=evaluation.teacher_id)
    except ValueError as exc:
        assert "Resolve every teacher review flag" in str(exc)
    else:
        raise AssertionError("Approval should require all review flags to be resolved")
