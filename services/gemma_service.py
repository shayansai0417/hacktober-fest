"""Direct multimodal inference with Google's Gemma model through GenAI SDK."""

from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import Future, ThreadPoolExecutor
from hashlib import sha256
from threading import Lock
from typing import Any

from google import genai
from google.genai import types
from pydantic import ValidationError

from config import settings
from schemas import EvaluationResult, ExtractedPage, ExtractedPageBatch, MarkingScheme
from services.grading_service import validate_result


class GemmaUnavailable(RuntimeError):
    pass


_ANSWER_READ_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="gemma-answer-read")
_ANSWER_READ_JOBS: dict[str, Future] = {}
_ANSWER_READ_JOBS_LOCK = Lock()


def _json_payload(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Gemma did not return a JSON object.")
    return json.loads(cleaned[start : end + 1])


def _client():
    if not settings.gemma_api_key:
        raise GemmaUnavailable("Add GEMMA_API_KEY in your environment to use live Gemma grading.")
    return genai.Client(api_key=settings.gemma_api_key, http_options=types.HttpOptions(timeout=settings.gemma_timeout_seconds * 1000))


def _api_error(exc: Exception) -> GemmaUnavailable:
    message = str(exc)
    lowered = message.lower()
    if "429" in message or "quota" in lowered or "resource_exhausted" in lowered:
        return GemmaUnavailable("Gemma is busy. Please wait a bit and retry.")
    if "timeout" in lowered or "deadline" in lowered:
        return GemmaUnavailable("Gemma took too long to respond. Your draft is saved; please retry.")
    return GemmaUnavailable("Gemma could not process this request. Check the API connection and retry.")


def _generate_json(client, contents: list[Any]) -> dict[str, Any]:
    """Make one JSON request, retrying only transient transport/API errors once."""
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = client.models.generate_content(model=settings.gemma_model, contents=contents)
        except Exception as exc:
            last_error = exc
            # Repeating a request that already waited for the full client timeout
            # doubles the teacher's wait and rarely helps. Keep the retry for
            # short transient server errors instead.
            if attempt == 0 and _is_transient(exc) and not _is_timeout(exc):
                time.sleep(0.8)
                continue
            raise _api_error(exc) from exc
        if not response.text:
            raise GemmaUnavailable("Gemma returned an empty response. Your draft is still available for retry.")
        try:
            return _json_payload(response.text)
        except (json.JSONDecodeError, ValueError) as exc:
            # A malformed response is a data-validation error, not a transient request failure.
            raise GemmaUnavailable(f"Gemma returned a response that could not be validated: {exc}") from exc
    raise _api_error(last_error or RuntimeError("The Gemma API request failed."))


def _grading_prompt(scheme: MarkingScheme, student_name: str, feedback_style: str, strictness: str, require_manual_review: bool, extracted_pages: list[ExtractedPage] | None = None) -> str:
    rubric = scheme.model_dump_json(indent=2)
    if extracted_pages is None:
        source_instruction = "Read the actual answer sheet image parts below. Images are in page order; use 1-based page numbers."
    else:
        source_instruction = "The following transcription was read from the actual page images by this same Gemma model in page-order batches. Combine continuations across pages, preserve uncertain mappings, and do not invent missing words."
    transcript = ""
    if extracted_pages is not None:
        transcript = "\nExtracted page answers:\n" + json.dumps([page.model_dump() for page in extracted_pages], ensure_ascii=False, indent=2)
    return f"""You are an assessment assistant. The teacher's marking scheme is the sole authority. Evaluate the student's answers against the listed questions. Preserve equations, units, crossed-out work and question mapping uncertainty. Do not guess illegible text. Give partial marks for demonstrated method or concepts. Accept equivalent wording or valid mathematical methods. Never penalize spelling unless the rubric says to. An uncertain/blank answer must be flagged for teacher review. Do not exceed each maximum mark. Return every question exactly once. If a student name is visible on the answer sheet, return it in student_name for a teacher identity check; do not use it to replace the teacher's selected student record.

Student: {student_name}
Grading calibration: {strictness}. Keep scoring consistent with the rubric; do not invent criteria to make grading stricter or more flexible.
Feedback style: {feedback_style}.
Require manual review on unclear handwriting: {str(require_manual_review).lower()}.
{source_instruction}
Marking scheme:
{rubric}{transcript}

Return ONLY valid JSON with this shape:
{{"student_name":"...","question_evaluations":[{{"question_number":1,"extracted_answer":"...","suggested_marks":0,"explanation":"...","correct_concepts":[],"missing_concepts":[],"incorrect_statements":[],"feedback":"...","confidence":0.0,"readability":"clear|partial|unclear|blank","page_number":1,"review_required":false}}],"overall_feedback":"..."}}
Confidence is between 0 and 1. Keep suggested_marks numeric and within the question maximum. Set review_required when handwriting, answer mapping or grading confidence is uncertain."""


def _extract_image_batch(client, page_bytes: list[bytes], first_page_number: int) -> tuple[list[ExtractedPage], str]:
    last_page = first_page_number + len(page_bytes) - 1
    prompt = f"""Read the handwritten content from these answer sheet images. These are original document pages {first_page_number} through {last_page}, in that order. Return each page using its original 1-based page number; include blank pages with an empty questions list. If a student name is visible on any page, return it for a teacher identity check. Preserve equations, units, question labels including subparts such as 1(a), crossed-out content, diagrams, and any unreadable text as uncertainty. For question_number, return a number for whole questions or the original label as text for subparts. Do not grade. Return ONLY JSON with this shape: {{\"student_name\":\"\",\"pages\":[{{\"page_number\":{first_page_number},\"questions\":[{{\"question_number\":\"1(a)\",\"extracted_answer\":\"...\",\"readability\":\"clear|partial|unclear|blank\",\"confidence\":0.0,\"page_number\":{first_page_number},\"mapping_uncertain\":false}}],\"notes\":\"\"}}]}}"""
    contents: list[Any] = [prompt]
    contents.extend(types.Part.from_bytes(data=data, mime_type="image/jpeg") for data in page_bytes)
    payload = _generate_json(client, contents)
    try:
        batch = ExtractedPageBatch.model_validate(payload)
    except ValidationError as exc:
        raise GemmaUnavailable(f"Gemma's handwriting extraction could not be validated: {exc}") from exc
    by_number = {page.page_number: page for page in batch.pages}
    expected = set(range(first_page_number, last_page + 1))
    if any(number not in expected for number in by_number):
        raise GemmaUnavailable("Gemma returned a handwriting page number outside the current page batch.")
    # Preserve missing pages as explicit empty pages so the grading prompt never treats omitted OCR as certainty.
    for number in sorted(expected - by_number.keys()):
        by_number[number] = ExtractedPage(page_number=number, notes="No extraction was returned for this page; teacher review required.")
    pages = [by_number[number] for number in range(first_page_number, last_page + 1)]
    for page in pages:
        for answer in page.questions:
            if answer.page_number is None:
                answer.page_number = page.page_number
    return pages, batch.student_name


def extract_answer_sheet(page_bytes: list[bytes]) -> tuple[list[ExtractedPage], list[str]]:
    """Read uploaded answer pages in batches without grading them."""
    if not page_bytes:
        raise GemmaUnavailable("Add at least one answer-sheet page before starting an evaluation.")
    batch_size = settings.gemma_image_batch_size
    groups = [
        (offset + 1, page_bytes[offset : offset + batch_size])
        for offset in range(0, len(page_bytes), batch_size)
    ]
    with ThreadPoolExecutor(max_workers=min(3, len(groups)), thread_name_prefix="gemma-answer-batch") as executor:
        futures = [
            executor.submit(_extract_image_batch, _client(), group, first_page)
            for first_page, group in groups
        ]
        results = [future.result() for future in futures]
    extracted: list[ExtractedPage] = []
    detected_names: list[str] = []
    for page_results, detected_name in results:
        extracted.extend(page_results)
        if detected_name.strip():
            detected_names.append(detected_name.strip())
    return extracted, detected_names


def queue_answer_sheet_read(page_bytes: list[bytes]) -> str:
    """Start (or reuse) background handwriting extraction for these pages."""
    if not page_bytes:
        raise GemmaUnavailable("Add at least one answer-sheet page before review.")
    digest = sha256()
    for page in page_bytes:
        digest.update(len(page).to_bytes(8, "big"))
        digest.update(page)
    job_id = digest.hexdigest()
    with _ANSWER_READ_JOBS_LOCK:
        future = _ANSWER_READ_JOBS.get(job_id)
        if future is None:
            # Bound the in-memory cache while leaving active requests alone.
            if len(_ANSWER_READ_JOBS) >= 64:
                for old_id, old_future in list(_ANSWER_READ_JOBS.items()):
                    if old_future.done():
                        _ANSWER_READ_JOBS.pop(old_id, None)
                        if len(_ANSWER_READ_JOBS) < 48:
                            break
            _ANSWER_READ_JOBS[job_id] = _ANSWER_READ_EXECUTOR.submit(extract_answer_sheet, page_bytes)
    return job_id


def answer_sheet_read_status(job_id: str) -> tuple[str, str | None]:
    with _ANSWER_READ_JOBS_LOCK:
        future = _ANSWER_READ_JOBS.get(job_id)
    if future is None:
        return "missing", None
    if not future.done():
        return "running", None
    error = future.exception()
    return ("failed", str(error)) if error else ("ready", None)


def wait_for_answer_sheet_read(job_id: str) -> tuple[list[ExtractedPage], list[str]]:
    with _ANSWER_READ_JOBS_LOCK:
        future = _ANSWER_READ_JOBS.get(job_id)
    if future is None:
        raise GemmaUnavailable("The background handwriting read is no longer available. Retry the review step.")
    try:
        result = future.result()
    except GemmaUnavailable:
        with _ANSWER_READ_JOBS_LOCK:
            _ANSWER_READ_JOBS.pop(job_id, None)
        raise
    except Exception as exc:
        with _ANSWER_READ_JOBS_LOCK:
            _ANSWER_READ_JOBS.pop(job_id, None)
        raise GemmaUnavailable("Gemma could not pre-read the answer sheet. You can retry grading from the original pages.") from exc
    with _ANSWER_READ_JOBS_LOCK:
        _ANSWER_READ_JOBS.pop(job_id, None)
    return result


def grade_pages(
    page_bytes: list[bytes],
    scheme: MarkingScheme,
    student_name: str,
    feedback_style: str = "Constructive and concise",
    strictness: str = "Balanced",
    require_manual_review: bool = True,
    *,
    extracted_pages: list[ExtractedPage] | None = None,
    detected_student_names: list[str] | None = None,
) -> EvaluationResult:
    """Read image parts and grade with Gemma; large papers are processed in image batches."""
    if not page_bytes:
        raise GemmaUnavailable("Add at least one answer-sheet page before starting an evaluation.")
    client = _client()
    batch_size = settings.gemma_image_batch_size
    missing_extraction = bool(extracted_pages) and any("No extraction was returned" in page.notes for page in extracted_pages)
    extracted_student_names = list(detected_student_names or [])
    if extracted_pages is not None:
        if not extracted_pages:
            raise GemmaUnavailable("Gemma could not read any answer-sheet pages. Review the upload and try again.")
        prompt = _grading_prompt(scheme, student_name, feedback_style, strictness, require_manual_review, extracted_pages)
        payload = _generate_json(client, [prompt])
    elif len(page_bytes) <= batch_size:
        prompt = _grading_prompt(scheme, student_name, feedback_style, strictness, require_manual_review)
        contents: list[Any] = [prompt]
        contents.extend(types.Part.from_bytes(data=data, mime_type="image/jpeg") for data in page_bytes)
        payload = _generate_json(client, contents)
    else:
        extracted, extracted_student_names = extract_answer_sheet(page_bytes)
        missing_extraction = any("No extraction was returned" in page.notes for page in extracted)
        prompt = _grading_prompt(scheme, student_name, feedback_style, strictness, require_manual_review, extracted)
        payload = _generate_json(client, [prompt])
    try:
        result = EvaluationResult.model_validate(payload)
        if missing_extraction:
            for item in result.question_evaluations:
                item.review_required = True
        detected_name = extracted_student_names[0] if extracted_student_names else result.student_name
        name_conflict = len({_name_key(name) for name in extracted_student_names}) > 1
        if detected_name and _name_key(detected_name) != _name_key(student_name):
            for item in result.question_evaluations:
                item.review_required = True
            identity_note = f"The answer sheet name was read as '{detected_name}', but the selected student is '{student_name}'. Confirm the record before approval."
            result.overall_feedback = f"{identity_note} {result.overall_feedback}".strip()
        if name_conflict:
            for item in result.question_evaluations:
                item.review_required = True
            result.overall_feedback = f"Student-name readings differ across page batches. Confirm the learner identity. {result.overall_feedback}".strip()
        return validate_result(result, scheme)
    except (ValidationError, ValueError) as exc:
        raise GemmaUnavailable(f"Gemma returned a response that could not be validated: {exc}") from exc


def extract_marking_scheme(page_bytes: list[bytes]) -> MarkingScheme:
    if not page_bytes:
        raise GemmaUnavailable("Add at least one marking-scheme page before extraction.")
    client = _client()
    prompt = _marking_scheme_prompt()
    parts: list[Any] = [prompt]
    parts.extend(types.Part.from_bytes(data=data, mime_type="image/jpeg") for data in page_bytes)
    try:
        payload = _generate_json(client, parts)
    except GemmaUnavailable as exc:
        if "response that could not be validated" in str(exc).lower():
            raise GemmaUnavailable(_marking_scheme_not_found()) from exc
        raise
    return _normalize_marking_scheme_payload(payload)


def extract_marking_scheme_text(source_text: str) -> MarkingScheme:
    """Extract a rubric from selectable PDF text with a compact text-only request."""
    compact_text = source_text.strip()
    if len(compact_text) < 40:
        raise GemmaUnavailable(_marking_scheme_not_found())
    client = _client()
    prompt = _marking_scheme_prompt() + " The source is selectable PDF text, not OCR; use its exact question labels and marks."
    try:
        payload = _generate_json(client, [prompt, compact_text[:60000]])
    except GemmaUnavailable as exc:
        if "response that could not be validated" in str(exc).lower():
            raise GemmaUnavailable(_marking_scheme_not_found()) from exc
        raise
    return _normalize_marking_scheme_payload(payload)


def _marking_scheme_prompt() -> str:
    return "Read the uploaded teacher marking scheme. Extract every question prompt, expected answer, maximum marks, key concepts, alternatives and partial-marking criteria. Preserve original question labels, including subparts such as 1(a), 1(b), and 2(c); put that label in number as text when needed. Do not invent questions or marks. If the document is not a marking scheme or its questions/marks cannot be read, return {\"questions\":[]} rather than guessing. Return only JSON: {\"questions\":[{\"number\":\"1(a)\",\"prompt\":\"\",\"expected_answer\":\"\",\"max_marks\":1,\"key_concepts\":[],\"alternatives\":[],\"criteria\":[],\"teacher_notes\":\"\"}]}"


def _normalize_marking_scheme_payload(payload: Any) -> MarkingScheme:
    if not isinstance(payload, dict) or not isinstance(payload.get("questions"), list) or not payload["questions"]:
        raise GemmaUnavailable(_marking_scheme_not_found())

    questions = []
    for index, item in enumerate(payload["questions"], 1):
        if not isinstance(item, dict):
            raise GemmaUnavailable(_marking_scheme_not_found())
        prompt_text = _first_text(item, "prompt", "question_text", "question", "text")
        if len(prompt_text) < 2:
            raise GemmaUnavailable(_marking_scheme_not_found())
        mark_value = item.get("max_marks")
        if mark_value is None:
            mark_value = item.get("marks", item.get("points"))
        max_marks = _parse_max_marks(mark_value)
        if max_marks is None:
            raise GemmaUnavailable(
                "Gemma found question text but could not read a valid maximum mark for every question. "
                "Upload a clearer marking scheme or correct the marks in the editor."
            )

        original_label = _first_text(item, "number", "label", "question_number", "question_no")
        if original_label:
            plain_number = re.fullmatch(r"(?:q\s*)?0*(\d+)", original_label, re.IGNORECASE)
            if not plain_number or int(plain_number.group(1)) != index:
                if not prompt_text.casefold().startswith(original_label.casefold()):
                    prompt_text = f"{original_label} — {prompt_text}"

        questions.append(
            {
                "number": index,
                "prompt": prompt_text,
                "expected_answer": _optional_text(item.get("expected_answer")),
                "max_marks": max_marks,
                "key_concepts": _string_list(item.get("key_concepts")),
                "alternatives": _string_list(item.get("alternatives")),
                "criteria": _string_list(item.get("criteria")),
                "teacher_notes": _optional_text(item.get("teacher_notes")),
            }
        )
    try:
        return MarkingScheme.model_validate({"questions": questions})
    except ValidationError as exc:
        raise GemmaUnavailable(
            "Gemma could not read a complete marking scheme. Check that each question has readable text and a maximum mark, "
            "or correct the extracted scheme in the editor."
        ) from exc


def _marking_scheme_not_found() -> str:
    return (
        "I couldn't identify a readable marking scheme in this file. Upload a clear rubric with question text and marks, "
        "or enter the scheme in the editor."
    )


def _first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            text = str(value).strip()
            if text and text.casefold() not in {"none", "null"}:
                return text
    return ""


def _optional_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _parse_max_marks(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:marks?|points?)?\s*", value, re.IGNORECASE)
        if not match:
            return None
        number = float(match.group(1))
    else:
        return None
    return number if math.isfinite(number) and number > 0 else None


def _is_transient(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in ("timeout", "deadline", "429", "500", "502", "503", "504", "temporarily unavailable", "resource_exhausted"))


def _is_timeout(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in ("timeout", "timed out", "deadline"))


def _name_key(value: str) -> str:
    return "".join(char.casefold() for char in value if char.isalnum())
