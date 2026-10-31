"""SQLAlchemy entities for teacher-owned assessments and review history."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    institution: Mapped[str] = mapped_column(String(180), default="")
    email: Mapped[str] = mapped_column(String(180), default="")
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    designation: Mapped[str] = mapped_column(String(120), default="")
    subject_specialization: Mapped[str] = mapped_column(String(180), default="")
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_demo_account: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_legacy_owner: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    feedback_style: Mapped[str] = mapped_column(String(60), default="Constructive and concise")
    grading_strictness: Mapped[str] = mapped_column(String(20), default="Balanced")
    manual_review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    students: Mapped[list["Student"]] = relationship(back_populates="teacher", cascade="all, delete-orphan")
    examinations: Mapped[list["Examination"]] = relationship(back_populates="teacher", cascade="all, delete-orphan")
    evaluations: Mapped[list["Evaluation"]] = relationship(back_populates="teacher", cascade="all, delete-orphan")
    auth_tokens: Mapped[list["AuthToken"]] = relationship(back_populates="teacher", cascade="all, delete-orphan")
    auth_sessions: Mapped[list["AuthSession"]] = relationship(back_populates="teacher", cascade="all, delete-orphan")


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    teacher: Mapped[Teacher] = relationship(back_populates="auth_tokens")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    session_version: Mapped[int] = mapped_column(Integer, nullable=False)
    remember: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    teacher: Mapped[Teacher] = relationship(back_populates="auth_sessions")


class LoginThrottle(Base):
    __tablename__ = "login_throttles"
    id: Mapped[int] = mapped_column(primary_key=True)
    email_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (UniqueConstraint("teacher_id", "student_code", name="uq_teacher_student_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    student_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    class_grade: Mapped[str] = mapped_column(String(80), default="")
    email: Mapped[str] = mapped_column(String(180), default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    teacher: Mapped[Teacher] = relationship(back_populates="students")
    evaluations: Mapped[list["Evaluation"]] = relationship(back_populates="student")


class Examination(Base):
    __tablename__ = "examinations"
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    class_grade: Mapped[str] = mapped_column(String(80), default="")
    academic_year: Mapped[str] = mapped_column(String(30), default="")
    exam_date: Mapped[date] = mapped_column(Date, default=date.today)
    total_marks: Mapped[float] = mapped_column(Float, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    teacher: Mapped[Teacher] = relationship(back_populates="examinations")
    questions: Mapped[list["Question"]] = relationship(back_populates="examination", cascade="all, delete-orphan", order_by="Question.number")
    evaluations: Mapped[list["Evaluation"]] = relationship(back_populates="examination")


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    examination_id: Mapped[int] = mapped_column(ForeignKey("examinations.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str] = mapped_column(Text, default="")
    max_marks: Mapped[float] = mapped_column(Float, nullable=False)
    key_concepts: Mapped[list] = mapped_column(JSON, default=list)
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    criteria: Mapped[list] = mapped_column(JSON, default=list)
    teacher_notes: Mapped[str] = mapped_column(Text, default="")
    examination: Mapped[Examination] = relationship(back_populates="questions")
    evaluations: Mapped[list["QuestionEvaluation"]] = relationship(back_populates="question")


class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="RESTRICT"), index=True)
    examination_id: Mapped[int] = mapped_column(ForeignKey("examinations.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="needs_review", index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    total_obtained: Mapped[float] = mapped_column(Float, default=0)
    percent: Mapped[float] = mapped_column(Float, default=0)
    overall_feedback: Mapped[str] = mapped_column(Text, default="")
    teacher_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(String(120), default="")
    ai_confidence: Mapped[float] = mapped_column(Float, default=0)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    teacher: Mapped[Teacher] = relationship(back_populates="evaluations")
    student: Mapped[Student] = relationship(back_populates="evaluations")
    examination: Mapped[Examination] = relationship(back_populates="evaluations")
    question_results: Mapped[list["QuestionEvaluation"]] = relationship(back_populates="evaluation", cascade="all, delete-orphan", order_by="QuestionEvaluation.question_number")
    answer_sheet: Mapped["AnswerSheet | None"] = relationship(back_populates="evaluation", cascade="all, delete-orphan", uselist=False)
    revisions: Mapped[list["TeacherRevision"]] = relationship(back_populates="evaluation", cascade="all, delete-orphan")


class AnswerSheet(Base):
    __tablename__ = "answer_sheets"
    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), unique=True)
    original_name: Mapped[str] = mapped_column(String(255), default="answer-sheet")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    evaluation: Mapped[Evaluation] = relationship(back_populates="answer_sheet")
    pages: Mapped[list["UploadedPage"]] = relationship(back_populates="answer_sheet", cascade="all, delete-orphan", order_by="UploadedPage.page_number")


class UploadedPage(Base):
    __tablename__ = "uploaded_pages"
    id: Mapped[int] = mapped_column(primary_key=True)
    answer_sheet_id: Mapped[int] = mapped_column(ForeignKey("answer_sheets.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), default="image/png")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    answer_sheet: Mapped[AnswerSheet] = relationship(back_populates="pages")


class QuestionEvaluation(Base):
    __tablename__ = "question_evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"), nullable=True)
    question_number: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, default="")
    expected_answer: Mapped[str] = mapped_column(Text, default="")
    extracted_answer: Mapped[str] = mapped_column(Text, default="")
    ai_marks: Mapped[float] = mapped_column(Float, default=0)
    final_marks: Mapped[float] = mapped_column(Float, default=0)
    max_marks: Mapped[float] = mapped_column(Float, default=0)
    ai_feedback: Mapped[str] = mapped_column(Text, default="")
    feedback: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    correct_concepts: Mapped[list] = mapped_column(JSON, default=list)
    missing_concepts: Mapped[list] = mapped_column(JSON, default=list)
    incorrect_statements: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    private_notes: Mapped[str] = mapped_column(Text, default="")
    evaluation: Mapped[Evaluation] = relationship(back_populates="question_results")
    question: Mapped[Question | None] = relationship(back_populates="evaluations")


class TeacherRevision(Base):
    __tablename__ = "teacher_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True)
    question_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    field_name: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_value: Mapped[str] = mapped_column(Text, default="")
    new_value: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    evaluation: Mapped[Evaluation] = relationship(back_populates="revisions")


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    evaluation_id: Mapped[int | None] = mapped_column(ForeignKey("evaluations.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

