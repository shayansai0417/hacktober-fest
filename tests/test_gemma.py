from __future__ import annotations

from types import SimpleNamespace

import pytest

from services import gemma_service
from services.gemma_service import GemmaUnavailable


def response(text):
    return SimpleNamespace(text=text)


def valid_response():
    return '{"student_name":"Avery Student","question_evaluations":[{"question_number":1,"extracted_answer":"4","suggested_marks":5,"explanation":"Correct","correct_concepts":["addition"],"missing_concepts":[],"incorrect_statements":[],"feedback":"Great","confidence":0.95,"readability":"clear","page_number":1,"review_required":false},{"question_number":2,"extracted_answer":"7","suggested_marks":4,"explanation":"One step missing","correct_concepts":["addition"],"missing_concepts":[],"incorrect_statements":[],"feedback":"Good","confidence":0.8,"readability":"clear","page_number":1,"review_required":false}],"overall_feedback":"Nice work."}'


class FakeModels:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []
    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.responses.pop(0)


def fake_client(models):
    return SimpleNamespace(models=models)


def test_mock_gemma_response_accepts_image_parts_and_exact_gemma_model(monkeypatch, scheme):
    models = FakeModels([response(valid_response())])
    monkeypatch.setattr(gemma_service, "_client", lambda: fake_client(models))
    result = gemma_service.grade_pages([b"image-bytes"], scheme, "Avery Student")
    assert result.question_evaluations[0].suggested_marks == 5
    call = models.calls[0]
    assert call["model"] == "gemma-4-26b-a4b-it"
    assert len(call["contents"]) == 2
    assert not isinstance(call["contents"][1], str)


def test_malformed_response_is_a_friendly_validation_error(monkeypatch, scheme):
    models = FakeModels([response("not json")])
    monkeypatch.setattr(gemma_service, "_client", lambda: fake_client(models))
    with pytest.raises(GemmaUnavailable, match="could not be validated"):
        gemma_service.grade_pages([b"image"], scheme, "Avery")


def test_invalid_mark_range_never_saves(monkeypatch, scheme):
    invalid = valid_response().replace('"suggested_marks":5', '"suggested_marks":9')
    models = FakeModels([response(invalid)])
    monkeypatch.setattr(gemma_service, "_client", lambda: fake_client(models))
    with pytest.raises(GemmaUnavailable, match="could not be validated"):
        gemma_service.grade_pages([b"image"], scheme, "Avery")


def test_timeout_is_reported_without_repeating_the_slow_request(monkeypatch, scheme):
    models = FakeModels(error=TimeoutError("request timeout"))
    monkeypatch.setattr(gemma_service, "_client", lambda: fake_client(models))
    with pytest.raises(GemmaUnavailable, match="timed out"):
        gemma_service.grade_pages([b"image"], scheme, "Avery")
    assert len(models.calls) == 1


def test_quota_error_is_reported_without_unbounded_retry(monkeypatch, scheme):
    models = FakeModels(error=RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded"))
    monkeypatch.setattr(gemma_service, "_client", lambda: fake_client(models))
    with pytest.raises(GemmaUnavailable, match="quota or rate limit"):
        gemma_service.grade_pages([b"image"], scheme, "Avery")
    assert len(models.calls) == 2


def test_long_answer_sheet_is_read_in_configured_image_batches(monkeypatch, scheme):
    first_batch = response('{"student_name":"Avery Student","pages":[{"page_number":1,"questions":[{"question_number":1,"extracted_answer":"4","readability":"clear","confidence":0.9}]},{"page_number":2,"questions":[{"question_number":2,"extracted_answer":"7","readability":"clear","confidence":0.9}]}]}')
    second_batch = response('{"student_name":"Avery Student","pages":[{"page_number":3,"questions":[],"notes":"continuation page"}]}')
    models = FakeModels([first_batch, second_batch, response(valid_response())])
    monkeypatch.setattr(gemma_service.settings, "gemma_image_batch_size", 2)
    monkeypatch.setattr(gemma_service, "_client", lambda: fake_client(models))
    result = gemma_service.grade_pages([b"page-1", b"page-2", b"page-3"], scheme, "Avery Student")
    assert len(result.question_evaluations) == 2
    assert len(models.calls) == 3
    assert all(not isinstance(part, str) for part in models.calls[0]["contents"][1:])
    assert all(not isinstance(part, str) for part in models.calls[1]["contents"][1:])
    assert models.calls[2]["contents"] and isinstance(models.calls[2]["contents"][0], str)


def test_student_name_mismatch_flags_every_question_for_review(monkeypatch, scheme):
    mismatch = valid_response().replace("Avery Student", "Different Learner")
    models = FakeModels([response(mismatch)])
    monkeypatch.setattr(gemma_service, "_client", lambda: fake_client(models))
    result = gemma_service.grade_pages([b"image"], scheme, "Avery Student")
    assert all(item.review_required for item in result.question_evaluations)
    assert "Confirm the record" in result.overall_feedback
