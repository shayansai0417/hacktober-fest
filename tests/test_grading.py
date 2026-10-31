from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas import EvaluationResult, MarkingScheme
from services.grading_service import result_status, score_total, validate_result


def test_full_partial_and_zero_marks(scheme):
    result = EvaluationResult.model_validate({"question_evaluations":[
        {"question_number":1,"suggested_marks":5,"confidence":.9,"readability":"clear"},
        {"question_number":2,"suggested_marks":2.5,"confidence":.8,"readability":"partial"},
    ]})
    validate_result(result, scheme)
    assert score_total([5, 2.5], [5, 5]) == 7.5
    assert score_total([0, 0], [5, 5]) == 0
    assert result_status("clear", .9, False) == "ai_suggested"
    assert result_status("unclear", .9, False) == "needs_review"


def test_marks_cannot_exceed_question_or_total(scheme):
    result = EvaluationResult.model_validate({"question_evaluations":[{"question_number":1,"suggested_marks":6},{"question_number":2,"suggested_marks":1}]})
    with pytest.raises(ValueError, match="exceed"):
        validate_result(result, scheme)
    with pytest.raises(ValueError, match="between zero"):
        score_total([5, 5.1], [5, 5])


def test_missing_duplicate_or_unknown_question_mappings_fail(scheme):
    missing = EvaluationResult.model_validate({"question_evaluations":[{"question_number":1,"suggested_marks":1}]})
    with pytest.raises(ValueError, match="did not return"):
        validate_result(missing, scheme)
    duplicate = EvaluationResult.model_validate({"question_evaluations":[{"question_number":1,"suggested_marks":1},{"question_number":1,"suggested_marks":2}]})
    with pytest.raises(ValueError, match="more than once"):
        validate_result(duplicate, scheme)
    unexpected = EvaluationResult.model_validate({"question_evaluations":[{"question_number":1,"suggested_marks":1},{"question_number":3,"suggested_marks":1}]})
    with pytest.raises(ValueError, match="unexpected"):
        validate_result(unexpected, scheme)


def test_marking_scheme_rejects_duplicate_question_numbers():
    with pytest.raises(ValidationError):
        MarkingScheme.model_validate({"questions":[{"number":1,"prompt":"one?","max_marks":1},{"number":1,"prompt":"two?","max_marks":1}]})
