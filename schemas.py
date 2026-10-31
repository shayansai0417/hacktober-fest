"""Validated business objects at the AI and upload boundaries."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExtractedAnswer(BaseModel):
    # Handwriting often uses subpart labels such as "1(a)"; keep them intact
    # in the transcription so the grading model can map them to the rubric.
    question_number: int | str | None = None
    extracted_answer: str = ""
    readability: Literal["clear", "partial", "unclear", "blank"] = "unclear"
    confidence: float = Field(default=0.0, ge=0, le=1)
    page_number: int | None = None
    mapping_uncertain: bool = False


class ExtractedPage(BaseModel):
    page_number: int = Field(ge=1)
    questions: list[ExtractedAnswer] = Field(default_factory=list)
    notes: str = ""


class ExtractedPageBatch(BaseModel):
    student_name: str = ""
    pages: list[ExtractedPage] = Field(default_factory=list)


class QuestionEvaluationOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question_number: int = Field(ge=1)
    extracted_answer: str = ""
    suggested_marks: float = Field(ge=0)
    explanation: str = ""
    correct_concepts: list[str] = Field(default_factory=list)
    missing_concepts: list[str] = Field(default_factory=list)
    incorrect_statements: list[str] = Field(default_factory=list)
    feedback: str = ""
    confidence: float = Field(default=0, ge=0, le=1)
    readability: Literal["clear", "partial", "unclear", "blank"] = "unclear"
    page_number: int | None = None
    review_required: bool = False


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    student_name: str = ""
    question_evaluations: list[QuestionEvaluationOut]
    overall_feedback: str = ""


class MarkingQuestion(BaseModel):
    number: int = Field(ge=1)
    prompt: str = Field(min_length=2)
    expected_answer: str = ""
    max_marks: float = Field(gt=0)
    key_concepts: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    criteria: list[str] = Field(default_factory=list)
    teacher_notes: str = ""


class MarkingScheme(BaseModel):
    questions: list[MarkingQuestion] = Field(min_length=1)

    @field_validator("questions")
    @classmethod
    def unique_question_numbers(cls, questions):
        numbers = [q.number for q in questions]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Question numbers must be unique.")
        return questions

    @model_validator(mode="after")
    def validate_total(self):
        if sum(q.max_marks for q in self.questions) <= 0:
            raise ValueError("The marking scheme must allocate marks.")
        return self

