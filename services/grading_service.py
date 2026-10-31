"""Deterministic score validation and review-state transitions."""

from __future__ import annotations

from schemas import EvaluationResult, MarkingScheme


def validate_result(result: EvaluationResult, scheme: MarkingScheme) -> EvaluationResult:
    expected = {q.number: q for q in scheme.questions}
    seen: set[int] = set()
    for item in result.question_evaluations:
        if item.question_number not in expected:
            raise ValueError(f"AI returned unexpected question {item.question_number}.")
        if item.question_number in seen:
            raise ValueError(f"AI returned question {item.question_number} more than once.")
        question = expected[item.question_number]
        if item.suggested_marks > question.max_marks:
            raise ValueError(f"AI marks for question {item.question_number} exceed its maximum.")
        seen.add(item.question_number)
    missing = sorted(set(expected) - seen)
    if missing:
        raise ValueError(f"AI did not return results for question(s): {', '.join(map(str, missing))}.")
    result.question_evaluations.sort(key=lambda item: item.question_number)
    return result


def score_total(scores: list[float], maximums: list[float]) -> float:
    if len(scores) != len(maximums):
        raise ValueError("Every question needs one score.")
    for score, maximum in zip(scores, maximums):
        if score < 0 or score > maximum:
            raise ValueError("Question marks must be between zero and the maximum.")
    return round(sum(scores), 2)


def result_status(readability: str, confidence: float, mapping_uncertain: bool, overridden: bool = False) -> str:
    if overridden:
        return "teacher_reviewed"
    if readability in {"unclear", "partial"} or confidence < 0.55 or mapping_uncertain:
        return "needs_review"
    return "ai_suggested"

