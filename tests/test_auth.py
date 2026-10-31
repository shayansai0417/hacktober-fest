from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from database.models import Evaluation, Examination, LoginThrottle, Question, QuestionEvaluation, Student, Teacher
from config import settings
from schemas import EvaluationResult, MarkingScheme, QuestionEvaluationOut
from services.analytics_service import evaluation_rows
from services.auth_service import (
    authenticate,
    change_password,
    consume_token,
    create_login_session,
    create_teacher,
    delete_teacher_workspace,
    hash_password,
    issue_token,
    resolve_login_session,
    revoke_login_session,
    send_token_email,
    verify_password,
)
from services.evaluation_service import get_evaluation, save_evaluation
from services.evaluation_service import approve_evaluation, review_overall_feedback
from services.export_service import class_csv, evaluation_pdf
from services.student_service import delete_student, update_student
from services.student_service import create_student


PASSWORD = "SecureTeacherPassword2026!"


def test_signup_hashes_password_normalizes_email_and_authenticates(db_session):
    teacher, token = create_teacher(
        db_session,
        name="Priya Shah",
        email="  PRIYA@School.EDU ",
        password=PASSWORD,
        institution="Northstar School",
    )

    assert token is None
    assert teacher.email == "priya@school.edu"
    assert teacher.password_hash != PASSWORD
    assert verify_password(teacher.password_hash, PASSWORD)
    found, error = authenticate(db_session, "Priya@School.edu", PASSWORD)
    assert found.id == teacher.id
    assert error == ""


def test_signup_rejects_duplicate_email_case_insensitively(db_session):
    create_teacher(db_session, name="Teacher One", email="one@school.edu", password=PASSWORD, institution="School")
    with pytest.raises(ValueError, match="already uses this email"):
        create_teacher(db_session, name="Teacher Two", email="ONE@SCHOOL.EDU", password=PASSWORD, institution="School")


def test_existing_demo_credentials_are_rejected_when_demo_is_disabled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "demo_login_enabled", False)
    demo = Teacher(name="Demo", institution="Demo", email="demo@papergrade.ai", password_hash=hash_password(PASSWORD), email_verified=True, is_demo_account=True)
    db_session.add(demo)
    db_session.flush()
    teacher, _ = authenticate(db_session, demo.email, PASSWORD)
    assert teacher is None


def test_invalid_password_is_rejected_and_login_is_throttled(db_session):
    teacher, _ = create_teacher(db_session, name="A Teacher", email="a@school.edu", password=PASSWORD, institution="School")
    found, _ = authenticate(db_session, teacher.email, "WrongPassword2026!")
    assert found is None
    assert db_session.scalar(select(LoginThrottle).where(LoginThrottle.email_hash.is_not(None))) is not None

    for _ in range(4):
        found, _ = authenticate(db_session, teacher.email, "WrongPassword2026!")
        assert found is None
    found, message = authenticate(db_session, teacher.email, PASSWORD)
    assert found is None
    assert "Too many sign-in attempts" in message


def test_verification_and_recovery_tokens_expire_and_are_single_use(db_session):
    teacher, _ = create_teacher(db_session, name="A Teacher", email="verify@school.edu", password=PASSWORD, institution="School")
    teacher.email_verified = False
    expired = issue_token(db_session, teacher, "verify_email", lifetime=timedelta(seconds=-1))
    assert consume_token(db_session, expired, "verify_email") is None

    token = issue_token(db_session, teacher, "verify_email")
    verified = consume_token(db_session, token, "verify_email")
    assert verified.id == teacher.id
    assert teacher.email_verified is True
    assert consume_token(db_session, token, "verify_email") is None

    reset = issue_token(db_session, teacher, "password_reset")
    assert consume_token(db_session, reset, "password_reset").id == teacher.id
    assert consume_token(db_session, reset, "password_reset") is None


def test_password_change_revokes_prior_session_versions(db_session):
    teacher, _ = create_teacher(db_session, name="A Teacher", email="change@school.edu", password=PASSWORD, institution="School")
    original_version = teacher.session_version
    change_password(db_session, teacher, PASSWORD, "AnotherSecurePassword2026!")
    assert teacher.session_version == original_version + 1
    assert verify_password(teacher.password_hash, "AnotherSecurePassword2026!")
    assert not verify_password(teacher.password_hash, PASSWORD)


def test_browser_sessions_are_hashed_expiring_and_revocable(db_session):
    teacher, _ = create_teacher(db_session, name="A Teacher", email="session@school.edu", password=PASSWORD, institution="School")
    auth_session, raw_token = create_login_session(db_session, teacher, remember=True)
    assert auth_session.token_hash != raw_token
    assert (auth_session.expires_at - auth_session.created_at).days >= 13
    assert resolve_login_session(db_session, raw_token)[1].id == teacher.id
    revoke_login_session(db_session, auth_session.id, teacher.id)
    assert resolve_login_session(db_session, raw_token) is None


def test_account_deletion_requires_password_and_keeps_other_teacher(db_session):
    owner_a = db_session.scalar(select(Teacher).where(Teacher.email == "test@example.com"))
    owner_b, _ = create_teacher(db_session, name="Teacher B", email="delete@school.edu", password=PASSWORD, institution="School B")
    db_session.add(Student(teacher_id=owner_b.id, name="Private Student", class_grade="Grade 8"))
    db_session.flush()
    with pytest.raises(ValueError, match="Password confirmation failed"):
        delete_teacher_workspace(db_session, owner_b.id, "WrongPassword2026!")
    assert db_session.get(Teacher, owner_b.id) is not None

    paths = delete_teacher_workspace(db_session, owner_b.id, PASSWORD)
    db_session.flush()
    assert paths == []
    assert db_session.get(Teacher, owner_b.id) is None
    assert db_session.get(Teacher, owner_a.id) is not None


def test_teacher_a_to_b_assessment_flow_stays_isolated(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    teacher_a, _ = create_teacher(db_session, name="Teacher A", email="a-flow@school.edu", password=PASSWORD, institution="School A")
    teacher_b, _ = create_teacher(db_session, name="Teacher B", email="b-flow@school.edu", password=PASSWORD, institution="School B")

    logged_in_a, error = authenticate(db_session, teacher_a.email, PASSWORD)
    assert logged_in_a.id == teacher_a.id and not error
    login_a, cookie_a = create_login_session(db_session, logged_in_a, remember=True)
    assert resolve_login_session(db_session, cookie_a)[0].id == login_a.id

    student = create_student(db_session, teacher_id=teacher_a.id, name="A Student", student_code="A-01", class_grade="Grade 8")
    scheme = MarkingScheme.model_validate({"questions": [{"number": 1, "prompt": "Solve 2 + 2", "expected_answer": "4", "max_marks": 5, "key_concepts": ["addition"]}]})
    exam = Examination(teacher_id=teacher_a.id, title="Arithmetic check", subject="Maths", class_grade="Grade 8", total_marks=5, is_demo=False, questions=[Question(number=1, prompt="Solve 2 + 2", expected_answer="4", max_marks=5, key_concepts=["addition"])])
    db_session.add(exam)
    db_session.flush()
    result = EvaluationResult(student_name=student.name, question_evaluations=[QuestionEvaluationOut(question_number=1, extracted_answer="4", suggested_marks=5, feedback="Correct.", confidence=.98, readability="clear")], overall_feedback="Excellent method.")
    evaluation = save_evaluation(db_session, teacher_a.id, student, exam, scheme, result, [("answer.jpg", b"private-page-bytes")], False, "test-model")
    db_session.commit()
    evaluation_id, evaluation_path = evaluation.id, evaluation.answer_sheet.pages[0].file_path

    own_evaluation = get_evaluation(db_session, evaluation_id, teacher_a.id)
    assert own_evaluation is not None
    assert evaluation_pdf(own_evaluation, teacher_id=teacher_a.id).startswith(b"%PDF")
    own_rows = evaluation_rows(db_session, teacher_a.id, False)
    assert class_csv(own_rows, teacher_id=teacher_a.id)
    review_overall_feedback(db_session, own_evaluation, "A teacher's final feedback.", teacher_id=teacher_a.id)
    approve_evaluation(db_session, own_evaluation, teacher_id=teacher_a.id)
    assert own_evaluation.status == "approved"

    revoke_login_session(db_session, login_a.id, teacher_a.id)
    logged_in_b, error = authenticate(db_session, teacher_b.email, PASSWORD)
    assert logged_in_b.id == teacher_b.id and not error
    login_b, cookie_b = create_login_session(db_session, logged_in_b, remember=False)
    assert resolve_login_session(db_session, cookie_b)[1].id == teacher_b.id
    assert get_evaluation(db_session, evaluation_id, teacher_b.id) is None
    assert evaluation_rows(db_session, teacher_b.id, False) == []
    with pytest.raises(PermissionError):
        review_overall_feedback(db_session, own_evaluation, "A cross-teacher edit", teacher_id=teacher_b.id)
    with pytest.raises(PermissionError):
        evaluation_pdf(own_evaluation, teacher_id=teacher_b.id)
    with pytest.raises(PermissionError):
        class_csv(own_rows, teacher_id=teacher_b.id)
    with pytest.raises(PermissionError):
        update_student(db_session, student.id, teacher_id=teacher_b.id, name="Changed", student_code="A-01", class_grade="Grade 8", email="")
    with pytest.raises(PermissionError):
        delete_student(db_session, student.id, teacher_id=teacher_b.id)
    assert Path(evaluation_path).read_bytes() == b"private-page-bytes"


def test_recovery_email_uses_configured_smtp_without_network(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_from_email", "noreply@example.test")
    monkeypatch.setattr(settings, "smtp_username", "smtp-user")
    monkeypatch.setattr(settings, "smtp_password", "smtp-secret")
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port) == ("smtp.example.test", 587)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self, context):
            self.tls_started = context is not None

        def login(self, username, password):
            assert (username, password) == ("smtp-user", "smtp-secret")

        def send_message(self, message):
            sent.append((self.tls_started, message))

    monkeypatch.setattr("services.auth_service.smtplib.SMTP", FakeSMTP)
    send_token_email("teacher@example.test", "A Teacher", "single-use-token", "password_reset", "https://papergrade.example")
    assert sent[0][0] is True
    assert sent[0][1]["To"] == "teacher@example.test"
    assert "auth_action=password_reset&token=single-use-token" in sent[0][1].get_content()


def test_teacher_queries_and_evaluation_creation_enforce_ownership(db_session):
    owner_a = db_session.scalar(select(Teacher).where(Teacher.email == "test@example.com"))
    owner_b, _ = create_teacher(db_session, name="Teacher B", email="teacher-b@school.edu", password=PASSWORD, institution="School B")
    student_a = db_session.scalar(select(Student).where(Student.teacher_id == owner_a.id))
    exam_a = db_session.scalar(select(Examination).where(Examination.teacher_id == owner_a.id))
    student_b = Student(teacher_id=owner_b.id, name="B Student", student_code="B-1", class_grade="Grade 8")
    exam_b = Examination(teacher_id=owner_b.id, title="B Exam", subject="Maths", total_marks=10, questions=[])
    db_session.add_all([student_b, exam_b])
    db_session.flush()
    eval_a = Evaluation(teacher_id=owner_a.id, student=student_a, examination=exam_a, is_demo=False)
    eval_b = Evaluation(teacher_id=owner_b.id, student=student_b, examination=exam_b, is_demo=False)
    result_b = QuestionEvaluation(
        question_number=1,
        question_text="B question",
        expected_answer="B answer",
        ai_marks=1,
        final_marks=1,
        max_marks=2,
        evaluation=eval_b,
    )
    eval_b.question_results.append(result_b)
    db_session.add_all([eval_a, eval_b])
    db_session.flush()

    assert get_evaluation(db_session, eval_b.id, owner_a.id) is None
    rows_a = evaluation_rows(db_session, owner_a.id, False)
    rows_b = evaluation_rows(db_session, owner_b.id, False)
    assert {row["id"] for row in rows_a} == {eval_a.id}
    assert {row["id"] for row in rows_b} == {eval_b.id}
    with pytest.raises(PermissionError):
        save_evaluation(db_session, owner_b.id, student_a, exam_a, None, None, [], False, "not-called")
    with pytest.raises(PermissionError):
        review_overall_feedback(db_session, eval_b, "attempted edit", teacher_id=owner_a.id)
    with pytest.raises(PermissionError):
        approve_evaluation(db_session, eval_b, teacher_id=owner_a.id)
    with pytest.raises(PermissionError):
        update_student(db_session, student_b.id, teacher_id=owner_a.id, name="Hijacked", student_code="B-1", class_grade="Grade 8", email="")
    with pytest.raises(PermissionError):
        delete_student(db_session, student_b.id, teacher_id=owner_a.id)
    with pytest.raises(PermissionError):
        class_csv(rows_b, teacher_id=owner_a.id)
    with pytest.raises(PermissionError):
        evaluation_pdf(eval_b, teacher_id=owner_a.id)
