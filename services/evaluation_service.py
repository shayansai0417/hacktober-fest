"""Persistence operations with explicit teacher-review auditing."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event, select
from sqlalchemy.orm import Session, selectinload

from config import settings
from database.models import ActivityLog, AnswerSheet, Evaluation, Examination, Question, QuestionEvaluation, Student, TeacherRevision, UploadedPage
from schemas import EvaluationResult, MarkingScheme
from services.grading_service import result_status, score_total
from utils.image_processing import sha256


def save_evaluation(
    session: Session,
    teacher_id: int,
    student: Student,
    exam: Examination,
    scheme: MarkingScheme,
    result: EvaluationResult,
    page_data: list[tuple[str, bytes]],
    is_demo: bool,
    model_name: str,
) -> Evaluation:
    if student.teacher_id != teacher_id or exam.teacher_id != teacher_id:
        raise PermissionError("An assessment can only be saved inside its owning teacher workspace.")
    if student.is_demo != is_demo or exam.is_demo != is_demo:
        raise ValueError("The selected student, examination, and workspace modes must match.")
    evaluation = Evaluation(
        teacher_id=teacher_id,
        student=student,
        examination=exam,
        status="needs_review",
        is_demo=is_demo,
        overall_feedback=result.overall_feedback,
        teacher_feedback=result.overall_feedback,
        model_name=model_name,
        ai_confidence=round(sum(q.confidence for q in result.question_evaluations) / max(len(result.question_evaluations), 1), 2),
    )
    session.add(evaluation)
    session.flush()
    q_by_number = {q.number: q for q in exam.questions}
    maximums: list[float] = []
    scores: list[float] = []
    for item in result.question_evaluations:
        q = q_by_number[item.question_number]
        status = result_status(item.readability, item.confidence, item.review_required)
        evaluation.question_results.append(QuestionEvaluation(
            question=q,
            question_number=item.question_number,
            question_text=q.prompt,
            expected_answer=q.expected_answer,
            extracted_answer=item.extracted_answer,
            ai_marks=item.suggested_marks,
            final_marks=item.suggested_marks,
            max_marks=q.max_marks,
            ai_feedback=item.feedback,
            feedback=item.feedback,
            rationale=item.explanation,
            correct_concepts=item.correct_concepts,
            missing_concepts=item.missing_concepts,
            incorrect_statements=item.incorrect_statements,
            confidence=item.confidence,
            page_number=item.page_number,
            review_flag=(status == "needs_review"),
        ))
        scores.append(item.suggested_marks)
        maximums.append(q.max_marks)
    evaluation.total_obtained = score_total(scores, maximums)
    evaluation.percent = round(evaluation.total_obtained / exam.total_marks * 100, 1) if exam.total_marks else 0
    if page_data:
        written_paths: list[Path] = []
        transaction_committed = False

        def _mark_uploads_committed(_session) -> None:
            nonlocal transaction_committed
            transaction_committed = True

        def _remove_uncommitted_uploads(_session) -> None:
            if transaction_committed:
                return
            for written_path in written_paths:
                try:
                    written_path.unlink(missing_ok=True)
                except OSError:
                    pass

        event.listen(session, "after_rollback", _remove_uncommitted_uploads, once=True)
        event.listen(session, "after_commit", _mark_uploads_committed, once=True)
        sheet = AnswerSheet(original_name=page_data[0][0])
        evaluation.answer_sheet = sheet
        for idx, (name, blob) in enumerate(page_data, 1):
            path = settings.upload_dir / f"eval-{evaluation.id}-{uuid4().hex[:12]}-page-{idx}.jpg"
            written_paths.append(path)
            path.write_bytes(blob)
            sheet.pages.append(UploadedPage(page_number=idx, file_path=str(path), mime_type="image/jpeg", sha256=sha256(blob), size_bytes=len(blob)))
    session.add(ActivityLog(teacher_id=teacher_id, evaluation_id=evaluation.id, action="evaluation_created", detail=f"Evaluation #{evaluation.id} ({'demo' if is_demo else model_name})"))
    session.flush()
    return evaluation


def _assert_evaluation_owner(evaluation: Evaluation, teacher_id: int) -> None:
    if evaluation.teacher_id != teacher_id:
        raise PermissionError("This evaluation does not belong to the signed-in teacher.")


def review_question(session: Session, evaluation: Evaluation, result: QuestionEvaluation, marks: float, feedback: str, notes: str, *, teacher_id: int) -> None:
    _assert_evaluation_owner(evaluation, teacher_id)
    if result.evaluation_id != evaluation.id:
        raise PermissionError("This question result does not belong to the selected evaluation.")
    if marks < 0 or marks > result.max_marks:
        raise ValueError(f"Marks must be between 0 and {result.max_marks:g}.")
    changes = {"final_marks": round(marks, 2), "feedback": feedback, "private_notes": notes}
    for field, value in changes.items():
        previous = getattr(result, field)
        if previous != value:
            session.add(TeacherRevision(evaluation_id=evaluation.id, question_number=result.question_number, field_name=field, previous_value=str(previous), new_value=str(value)))
            setattr(result, field, value)
    result.overridden = (result.final_marks != result.ai_marks) or (result.feedback != result.ai_feedback)
    result.review_flag = False
    scores = [r.final_marks for r in evaluation.question_results]
    maximums = [r.max_marks for r in evaluation.question_results]
    evaluation.total_obtained = score_total(scores, maximums)
    maximum = sum(maximums)
    evaluation.percent = round(evaluation.total_obtained / maximum * 100, 1) if maximum else 0
    evaluation.status = "teacher_reviewed"
    evaluation.approved_at = None


def restore_suggestion(session: Session, evaluation: Evaluation, result: QuestionEvaluation, *, teacher_id: int) -> None:
    _assert_evaluation_owner(evaluation, teacher_id)
    if result.evaluation_id != evaluation.id:
        raise PermissionError("This question result does not belong to the selected evaluation.")
    review_question(session, evaluation, result, result.ai_marks, result.ai_feedback, result.private_notes, teacher_id=teacher_id)


def review_overall_feedback(session: Session, evaluation: Evaluation, feedback: str, *, teacher_id: int) -> None:
    _assert_evaluation_owner(evaluation, teacher_id)
    if evaluation.status == "approved":
        raise ValueError("Reopen this evaluation before editing teacher feedback.")
    previous = evaluation.teacher_feedback
    if previous != feedback:
        session.add(TeacherRevision(
            evaluation_id=evaluation.id,
            question_number=None,
            field_name="teacher_feedback",
            previous_value=previous or "",
            new_value=feedback,
        ))
    evaluation.teacher_feedback = feedback
    evaluation.status = "teacher_reviewed"
    evaluation.approved_at = None


def approve_evaluation(session: Session, evaluation: Evaluation, *, teacher_id: int) -> None:
    _assert_evaluation_owner(evaluation, teacher_id)
    if any(result.review_flag for result in evaluation.question_results):
        raise ValueError("Resolve every teacher review flag before approving this evaluation.")
    evaluation.status = "approved"
    evaluation.approved_at = datetime.now(timezone.utc)
    session.add(ActivityLog(teacher_id=evaluation.teacher_id, evaluation_id=evaluation.id, action="evaluation_approved", detail=f"Teacher approved evaluation #{evaluation.id}"))


def reopen_evaluation(session: Session, evaluation: Evaluation, *, teacher_id: int) -> None:
    _assert_evaluation_owner(evaluation, teacher_id)
    if evaluation.status != "approved":
        return
    session.add(TeacherRevision(evaluation_id=evaluation.id, field_name="approval_status", previous_value="approved", new_value="teacher_reviewed"))
    evaluation.status = "teacher_reviewed"
    evaluation.approved_at = None


def get_evaluation(session: Session, evaluation_id: int, teacher_id: int) -> Evaluation | None:
    return session.scalar(select(Evaluation).where(Evaluation.id == evaluation_id, Evaluation.teacher_id == teacher_id).options(
        selectinload(Evaluation.student), selectinload(Evaluation.examination), selectinload(Evaluation.question_results), selectinload(Evaluation.answer_sheet).selectinload(AnswerSheet.pages)
    ))

