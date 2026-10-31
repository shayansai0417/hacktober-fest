"""Five-step upload, rubric review, and AI grading workflow."""

from __future__ import annotations

import html
import json
import re
from datetime import date

import streamlit as st
from pydantic import ValidationError
from sqlalchemy import select

from components.ui import page_header
from config import ROOT_DIR, settings
from database.db import session_scope
from database.models import Examination, Question, Student, Teacher
from database.seed import SAMPLE_SHEET
from pages._common import teacher_id
from schemas import EvaluationResult, ExtractedPage, MarkingScheme
from services.evaluation_service import save_evaluation
from services.gemma_service import (
    GemmaUnavailable,
    extract_marking_scheme,
    extract_marking_scheme_text,
    grade_pages,
    queue_answer_sheet_read,
    wait_for_answer_sheet_read,
)
from utils.image_processing import expand_uploads, extract_pdf_text, validate_file


STEPS = ["Details", "Answer sheet", "Marking scheme", "Review & start"]
SAMPLE_SCHEME_PATH = ROOT_DIR / "sample_data" / "demo_marking_scheme.json"
DETAIL_WIDGET_KEYS = (
    "detail_exam_title",
    "detail_subject",
    "detail_class",
    "detail_year",
    "detail_date",
    "detail_total",
    "detail_student_choice",
    "detail_student_name",
    "detail_student_code",
)
DETAIL_ALWAYS_VISIBLE_KEYS = DETAIL_WIDGET_KEYS[:7]


def _init_draft() -> None:
    if "evaluation_draft" not in st.session_state:
        st.session_state.evaluation_draft = {"step": 1, "pages": [], "details": None, "scheme": None}
    draft = st.session_state.evaluation_draft
    if "scheme_editor" not in st.session_state:
        saved_text = draft.get("scheme_text")
        if not saved_text and draft.get("scheme") is not None:
            try:
                saved_scheme = draft["scheme"]
                saved_text = saved_scheme if isinstance(saved_scheme, str) else MarkingScheme.model_validate(saved_scheme).model_dump_json(indent=2)
            except (ValidationError, TypeError):
                saved_text = None
        if saved_text:
            st.session_state.scheme_editor = saved_text
        elif st.session_state.get("workspace_mode", "demo") == "demo":
            st.session_state.scheme_editor = SAMPLE_SCHEME_PATH.read_text(encoding="utf-8")
        else:
            st.session_state.scheme_editor = json.dumps({"questions": [{"number": 1, "prompt": "", "expected_answer": "", "max_marks": 1, "key_concepts": [], "alternatives": [], "criteria": [], "teacher_notes": ""}]}, indent=2)
    _migrate_legacy_demo_scheme()


def _migrate_legacy_demo_scheme() -> None:
    """Replace only the untouched, built-in 15-mark rubric from older sessions."""
    if st.session_state.get("workspace_mode", "demo") != "demo":
        return
    if st.session_state.get("_demo_sample_scheme_migrated"):
        return
    draft = st.session_state.evaluation_draft
    try:
        current = MarkingScheme.model_validate_json(st.session_state.scheme_editor)
        sample = MarkingScheme.model_validate_json(SAMPLE_SCHEME_PATH.read_text(encoding="utf-8"))
    except (ValidationError, TypeError, OSError):
        return

    # Match the complete previous built-in rubric (including criteria) so a
    # teacher's own rubric is never silently replaced.
    legacy_criteria = [
        ["2 marks for isolating 3x", "2 marks for x = 5", "1 mark for clear working"],
        ["2 marks for method", "2 marks for answer", "1 mark for units"],
        ["partial credit for a correct conversion"],
    ]
    legacy_matches = len(current.questions) == len(sample.questions) == 3
    if legacy_matches:
        for old, new, criteria in zip(current.questions, sample.questions, legacy_criteria):
            legacy_matches = legacy_matches and (
                old.number == new.number
                and old.prompt == new.prompt
                and old.expected_answer == new.expected_answer
                and old.max_marks == 5
                and old.key_concepts == new.key_concepts
                and old.alternatives == new.alternatives
                and old.criteria == criteria
            )
    if legacy_matches:
        updated_text = sample.model_dump_json(indent=2)
        st.session_state.scheme_editor = updated_text
        draft["scheme_text"] = updated_text
        draft["scheme"] = None
        details = draft.get("details") or {}
        if details.get("total_marks") == 15:
            details["total_marks"] = 100.0
            if draft.get("step") == 1:
                st.session_state._restore_evaluation_details = True
        st.session_state._demo_sample_scheme_migrated = True


def _scaled_demo_sample_scheme(total_marks: float) -> MarkingScheme:
    """Scale the untouched example rubric to the teacher's chosen exam total."""
    sample = MarkingScheme.model_validate_json(SAMPLE_SCHEME_PATH.read_text(encoding="utf-8"))
    base_total = sum(question.max_marks for question in sample.questions)
    values = sample.model_dump()
    allocated = 0.0
    for index, question in enumerate(values["questions"]):
        base_question = sample.questions[index]
        if index == len(values["questions"]) - 1:
            new_max = round(float(total_marks) - allocated, 2)
        else:
            new_max = round(float(total_marks) * base_question.max_marks / base_total, 2)
            allocated += new_max
        factor = new_max / base_question.max_marks
        question["max_marks"] = new_max
        question["criteria"] = [
            re.sub(
                r"(\d+(?:\.\d+)?)\s+(marks?)\b",
                lambda match: f"{float(match.group(1)) * factor:g} {match.group(2)}",
                criterion,
            )
            for criterion in question["criteria"]
        ]
    return MarkingScheme.model_validate(values)


def _scale_untouched_demo_scheme(total_marks: float, previous_total: float | None) -> None:
    """Keep the built-in demo rubric aligned when the exam total is changed."""
    if st.session_state.get("workspace_mode", "demo") != "demo":
        return
    try:
        current = MarkingScheme.model_validate_json(st.session_state.scheme_editor)
        candidate_totals = {100.0}
        if previous_total is not None:
            candidate_totals.add(float(previous_total))
        is_untouched_sample = any(
            current.model_dump() == _scaled_demo_sample_scheme(candidate_total).model_dump()
            for candidate_total in candidate_totals
        )
        if is_untouched_sample:
            st.session_state.scheme_editor = _scaled_demo_sample_scheme(total_marks).model_dump_json(indent=2)
            st.session_state.evaluation_draft["scheme"] = None
    except (ValidationError, TypeError, ValueError, OSError):
        return


def _teacher_students() -> list[dict]:
    demo = st.session_state.get("workspace_mode", "demo") == "demo"
    with session_scope() as session:
        owner_id = teacher_id(session)
        rows = session.scalars(select(Student).where(Student.teacher_id == owner_id, Student.is_demo.is_(demo)).order_by(Student.name)).all()
        return [{"id": student.id, "name": student.name, "code": student.student_code, "class_grade": student.class_grade} for student in rows]


def _progress(step: int) -> None:
    cols = st.columns(len(STEPS))
    for i, (col, label) in enumerate(zip(cols, STEPS), 1):
        klass = "step-active" if i == step else ("step-done" if i < step else "")
        marker = "✓" if i < step else f"0{i}"
        with col:
            st.markdown(f"<div class='workflow-step {klass}'><span>{marker}</span><div><small>STEP {i}</small><strong>{label}</strong></div></div>", unsafe_allow_html=True)
    st.markdown("<div class='workflow-rule'></div>", unsafe_allow_html=True)


def _jump(step: int) -> None:
    st.session_state.evaluation_draft["step"] = step
    if step == 1:
        st.session_state._restore_evaluation_details = True
    st.rerun()


def _clear_answer_prefetch(draft: dict) -> None:
    draft.pop("answer_prefetch_job", None)
    draft.pop("answer_prefetch_result", None)
    draft.pop("answer_prefetch_error", None)


def _step_details(draft: dict) -> None:
    students = _teacher_students()
    labels = ["Add a new student"] + [f"{s['name']} · {s['code'] or 'no ID'} · {s['class_grade'] or 'no class'}" for s in students]
    saved = draft.get("details") or {}
    saved_student_id = saved.get("student_id")
    student_index = next((index + 1 for index, student in enumerate(students) if student["id"] == saved_student_id), 0)
    try:
        saved_exam_date = date.fromisoformat(saved["exam_date"]) if saved.get("exam_date") else date.today()
    except (TypeError, ValueError):
        saved_exam_date = date.today()
    defaults = {
        "detail_exam_title": saved.get("title", ""),
        "detail_subject": saved.get("subject", ""),
        "detail_class": saved.get("class_grade", ""),
        "detail_year": saved.get("academic_year", str(date.today().year)),
        "detail_date": saved_exam_date,
        "detail_total": saved.get("total_marks", 100.0),
        "detail_student_choice": labels[student_index],
        "detail_student_name": saved.get("student_name", ""),
        "detail_student_code": saved.get("student_code") or "",
    }
    # Draft data is authoritative on Back. Seed widgets on first entry too, so
    # a stale total from an earlier app version cannot keep the old 15-mark value.
    restore = st.session_state.pop("_restore_evaluation_details", False)
    first_entry = not st.session_state.get("_evaluation_details_initialized", False)
    widgets_were_cleaned = bool(saved) and any(key not in st.session_state for key in DETAIL_ALWAYS_VISIBLE_KEYS)
    restore = restore or first_entry or widgets_were_cleaned
    for key, value in defaults.items():
        if restore or first_entry:
            st.session_state[key] = value
        elif key == "detail_student_choice" and st.session_state.get(key) not in labels:
            st.session_state[key] = value
    st.session_state._evaluation_details_initialized = True
    with st.form("evaluation_details"):
        st.markdown("#### Assessment details")
        left, right = st.columns(2)
        with left:
            exam_title = st.text_input("Examination title", placeholder="e.g. Algebra checkpoint", key="detail_exam_title")
            subject = st.text_input("Subject", placeholder="Mathematics", key="detail_subject")
            class_grade = st.text_input("Class / grade", placeholder="Grade 8", key="detail_class")
            academic_year = st.text_input("Academic year", key="detail_year")
        with right:
            exam_date = st.date_input("Examination date", key="detail_date")
            total_marks = st.number_input("Examination total marks", min_value=1.0, max_value=1000.0, step=1.0, key="detail_total")
            existing = st.selectbox("Student record", labels, key="detail_student_choice")
            if existing == labels[0]:
                student_name = st.text_input("Student name", placeholder="Full name", key="detail_student_name")
                student_code = st.text_input("Student ID (optional)", placeholder="e.g. PG-024", key="detail_student_code")
            else:
                selected_student = students[labels.index(existing) - 1]
                student_name, student_code = selected_student["name"], selected_student["code"] or ""
                st.caption(f"Class: {selected_student['class_grade'] or 'Not set'}")
        go = st.form_submit_button("Continue to answer sheet", type="primary", use_container_width=True)
    if go:
        if not exam_title.strip() or not subject.strip() or not class_grade.strip():
            st.error("Add the examination title, subject, and class before continuing.")
        elif existing == labels[0] and not student_name.strip():
            st.error("Add a student name or select an existing student record.")
        else:
            _scale_untouched_demo_scheme(float(total_marks), saved.get("total_marks"))
            draft["details"] = {"title": exam_title.strip(), "subject": subject.strip(), "class_grade": class_grade.strip(), "academic_year": academic_year.strip(), "exam_date": exam_date.isoformat(), "total_marks": float(total_marks), "student_name": student_name.strip(), "student_code": student_code.strip() or None, "student_id": None if existing == labels[0] else selected_student["id"]}
            _jump(2)


def _step_upload(draft: dict) -> None:
    st.markdown("#### Add answer sheet pages")
    demo = st.session_state.workspace_mode == "demo"
    if demo and not settings.live_ready:
        st.info("Demo records stay labeled. Without GEMMA_API_KEY, grading uses a repeatable sample result; add the key to analyze uploaded handwriting with Gemma.")
    files = st.file_uploader("Upload one or more JPG, PNG, or PDF files", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True, key="answer_sheet_uploader", help=f"Up to {settings.max_upload_mb} MB per file. PDFs are split into page images.")
    controls = st.columns(2)
    with controls[0]:
        if st.button("Add uploaded files", icon=":material/upload_file:", disabled=not files, use_container_width=True):
            try:
                additions = expand_uploads([(f.name, f.getvalue()) for f in files], settings.max_upload_mb)
                existing_hashes = {__import__("hashlib").sha256(data).hexdigest() for _, data in draft["pages"]}
                for item in additions:
                    digest = __import__("hashlib").sha256(item[1]).hexdigest()
                    if digest not in existing_hashes:
                        draft["pages"].append(item)
                        existing_hashes.add(digest)
                _clear_answer_prefetch(draft)
                st.success(f"Prepared {len(additions)} page(s) for review.")
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
    with controls[1]:
        if st.button("Use sample handwritten sheet", icon=":material/description:", disabled=not demo, use_container_width=True):
            try:
                additions = expand_uploads([(SAMPLE_SHEET.name, SAMPLE_SHEET.read_bytes())], settings.max_upload_mb)
                draft["pages"] = additions
                _clear_answer_prefetch(draft)
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))

    if draft["pages"]:
        st.markdown(f"**{len(draft['pages'])} page(s) ready** · Arrange the order or remove pages before continuing.")
        proposed: list[tuple[int, str, bytes, bool]] = []
        for idx, (name, content) in enumerate(draft["pages"]):
            left, right = st.columns([1, 3])
            with left:
                st.image(content, caption=f"Page {idx + 1}", use_container_width=True)
            with right:
                st.markdown(f"**{name}**")
                order = st.selectbox("Page order", list(range(1, len(draft["pages"]) + 1)), index=idx, key=f"page_order_{idx}", label_visibility="collapsed")
                remove = st.checkbox("Remove this page", key=f"page_remove_{idx}")
            proposed.append((order, name, content, remove))
        a, b = st.columns(2)
        with a:
            if st.button("Apply page order and continue", type="primary", use_container_width=True):
                kept = sorted((x for x in proposed if not x[3]), key=lambda x: x[0])
                if not kept:
                    st.error("Keep at least one page in the answer sheet.")
                else:
                    draft["pages"] = [(name, content) for _, name, content, _ in kept]
                    _clear_answer_prefetch(draft)
                    _jump(3)
        with b:
            if st.button("Back", use_container_width=True):
                _jump(1)
    else:
        if st.button("Back", use_container_width=True):
            _jump(1)


def _extract_scheme(files) -> None:
    if not files:
        st.warning("Upload at least one marking-scheme page first.")
        return
    try:
        uploads = [(file.name, file.getvalue()) for file in files]
        source_text = ""
        if all(name.lower().endswith(".pdf") for name, _ in uploads):
            try:
                total_bytes = 0
                text_pages = []
                for name, content in uploads:
                    validate_file(name, content, settings.max_upload_mb)
                    total_bytes += len(content)
                    if total_bytes > settings.max_upload_mb * 4 * 1024 * 1024:
                        raise ValueError("Combined marking-scheme uploads exceed the 4× file size limit.")
                    text_pages.append(extract_pdf_text(content))
                source_text = "\n\n".join(text_pages).strip()
            except (ValueError, RuntimeError):
                source_text = ""
        if len(source_text) >= 60:
            with st.spinner("Reading marking scheme…"):
                candidate = extract_marking_scheme_text(source_text)
        else:
            pages = expand_uploads(uploads, settings.max_upload_mb)
            with st.spinner("Reading marking scheme…"):
                candidate = extract_marking_scheme([content for _, content in pages])
        st.session_state.scheme_editor = candidate.model_dump_json(indent=2)
        st.session_state.evaluation_draft["scheme_text"] = st.session_state.scheme_editor
        st.session_state.evaluation_draft["scheme"] = candidate.model_dump()
        st.success(f"Read {len(candidate.questions)} question(s). Review the extracted questions and marks below before continuing.")
    except Exception as exc:
        st.error(str(exc))


def _step_scheme(draft: dict) -> None:
    st.markdown("#### Upload your marking scheme")
    st.caption("Upload the rubric as a photo, scan, or PDF, just like the answer sheet. Gemma will read the questions, expected answers, marks, and partial-credit rules; review the result before grading.")
    files = st.file_uploader(
        "Marking scheme pages",
        type=["jpg", "jpeg", "png", "pdf"],
        accept_multiple_files=True,
        key="scheme_upload",
        help=f"Up to {settings.max_upload_mb} MB per file. PDFs are split into page images.",
    )
    demo = st.session_state.get("workspace_mode", "demo") == "demo"
    if demo and settings.live_ready:
        st.info(f"Gemma is available in the demo workspace. Reading this rubric sends its content to {settings.gemma_model}; the resulting assessment stays labeled as demo data.")
    elif not settings.live_ready:
        st.warning("Add GEMMA_API_KEY to enable AI extraction. You can still review the sample or edit the scheme below.")
    if st.button(
        "Read marking scheme with Gemma",
        icon=":material/auto_awesome:",
        type="primary",
        disabled=not files or not settings.live_ready,
        use_container_width=True,
    ):
        _extract_scheme(files)

    try:
        current_scheme = MarkingScheme.model_validate_json(st.session_state.scheme_editor)
    except (ValidationError, TypeError):
        current_scheme = None
    if current_scheme:
        st.markdown("#### Extracted questions · review before grading")
        st.dataframe(
            [{"Question": f"Q{q.number}", "Question / prompt": q.prompt, "Expected answer": q.expected_answer, "Marks": q.max_marks, "Key concepts": ", ".join(q.key_concepts), "Partial-credit criteria": "; ".join(q.criteria)} for q in current_scheme.questions],
            hide_index=True,
            use_container_width=True,
        )
        current_total = sum(q.max_marks for q in current_scheme.questions)
        expected_total = draft.get("details", {}).get("total_marks")
        if expected_total is not None and abs(current_total - expected_total) > 0.01:
            st.warning(f"Extracted marks add up to {current_total:g}; this examination is set to {expected_total:g}. Adjust the scheme or examination total before continuing.")

    # Keep the continue action next to the extracted table, independently of
    # the optional editor below.
    scheme_text = st.session_state.scheme_editor
    draft["scheme_text"] = scheme_text
    draft["scheme"] = scheme_text
    prev, go = st.columns(2)
    with prev:
        back = st.button("Back to answer sheet", use_container_width=True)
    with go:
        next_step = st.button("Review assessment", type="primary", use_container_width=True)
    if back:
        _jump(2)
    if next_step:
        try:
            parsed = MarkingScheme.model_validate_json(scheme_text)
            total = sum(q.max_marks for q in parsed.questions)
            expected = draft["details"]["total_marks"]
            if abs(total - expected) > 0.01:
                st.error(f"Your questions total {total:g} marks, while the examination is set to {expected:g}. Adjust one of them before continuing.")
            else:
                # Persist the validated object, not the JSON text. The review/start
                # steps consume this as a Python dictionary.
                draft["scheme"] = parsed.model_dump()
                if settings.live_ready and len(draft["pages"]) > settings.gemma_image_batch_size and not draft.get("answer_prefetch_result"):
                    try:
                        draft["answer_prefetch_job"] = queue_answer_sheet_read([content for _, content in draft["pages"]])
                    except GemmaUnavailable as exc:
                        draft["answer_prefetch_error"] = str(exc)
                _jump(4)
        except Exception as exc:
            if isinstance(exc, ValidationError):
                messages = "; ".join(error["msg"] for error in exc.errors())
                st.error(f"Check the marking scheme: {messages}")
            else:
                st.error(f"Check the marking scheme: {exc}")

    with st.expander("Optional: edit the extracted marking scheme", expanded=False):
        st.caption("This is an optional fallback for hand-entered corrections. Question marks must add up to the examination total.")
        st.text_area("Marking scheme JSON", key="scheme_editor", height=360, help="The uploaded rubric is converted into this editable structure. You can adjust question prompts, answers, marks, concepts, and criteria here.")


def _demo_result(scheme: MarkingScheme, student_name: str) -> EvaluationResult:
    results = []
    for index, q in enumerate(scheme.questions):
        factor = (1.0, 0.6, 0.8)[index % 3]
        score = round(q.max_marks * factor, 2)
        results.append({"question_number": q.number, "extracted_answer": f"Demonstration sample response for question {q.number}.", "suggested_marks": score, "explanation": "This fixed sample score demonstrates the review workflow. The answer image was not analyzed.", "correct_concepts": q.key_concepts[:1], "missing_concepts": q.key_concepts[1:2], "incorrect_statements": [], "feedback": "Sample feedback only · configure GEMMA_API_KEY to evaluate uploaded handwriting with Gemma.", "confidence": 0.86, "readability": "clear", "page_number": 1, "review_required": False})
    return EvaluationResult(student_name=student_name, question_evaluations=results, overall_feedback="Demonstration result only. No AI inference was performed on the uploaded answer sheet.")


def _start(draft: dict) -> None:
    details = draft["details"]
    try:
        scheme = MarkingScheme.model_validate(draft["scheme"])
        if abs(sum(q.max_marks for q in scheme.questions) - details["total_marks"]) > 0.01:
            st.error("The marking scheme total no longer matches the examination total.")
            return
        if not draft["pages"]:
            st.error("Add at least one answer sheet page first.")
            return
        demo = st.session_state.workspace_mode == "demo"
        use_gemma = settings.live_ready
        if not demo and not use_gemma:
            st.error("Live Gemma mode is selected, but GEMMA_API_KEY is not configured. Your uploaded files and form values are still here.")
            return
        # Snapshot teacher preferences before grading. The model call needs these
        # values, and the database session must not stay open during inference.
        with session_scope() as session:
            owner_id = teacher_id(session)
            teacher_settings = session.get(Teacher, owner_id)
            if teacher_settings is None:
                raise RuntimeError("Teacher workspace was not initialized. Refresh and try again.")
            owner_id = teacher_settings.id
            feedback_style = teacher_settings.feedback_style
            grading_strictness = teacher_settings.grading_strictness
            manual_review_required = teacher_settings.manual_review_required
        with st.status("Preparing the evaluation", expanded=True) as status:
            if use_gemma:
                extracted_pages = None
                detected_names = None
                use_prefetch = len(draft["pages"]) > settings.gemma_image_batch_size
                cached_read = draft.get("answer_prefetch_result") if use_prefetch else None
                if cached_read:
                    try:
                        extracted_pages = [ExtractedPage.model_validate(page) for page in cached_read["pages"]]
                        detected_names = list(cached_read.get("student_names", []))
                    except (ValidationError, TypeError, KeyError):
                        draft.pop("answer_prefetch_result", None)
                job_id = draft.get("answer_prefetch_job") if use_prefetch else None
                if extracted_pages is None and job_id:
                    try:
                        extracted_pages, detected_names = wait_for_answer_sheet_read(job_id)
                        draft["answer_prefetch_result"] = {
                            "pages": [page.model_dump() for page in extracted_pages],
                            "student_names": detected_names,
                        }
                        draft["answer_prefetch_job"] = None
                    except GemmaUnavailable as exc:
                        draft["answer_prefetch_job"] = None
                        draft["answer_prefetch_error"] = str(exc)
                        raise GemmaUnavailable("Gemma could not finish reading the answer pages. Your draft is saved; click Start again to retry.") from exc
                st.write(f"Analyzing {len(draft['pages'])} page(s) against the reviewed marking scheme with {settings.gemma_model}.")
                result = grade_pages(
                    [content for _, content in draft["pages"]],
                    scheme,
                    details["student_name"],
                    feedback_style,
                    grading_strictness,
                    manual_review_required,
                    extracted_pages=extracted_pages,
                    detected_student_names=detected_names,
                )
                model_name = settings.gemma_model
                st.write("Gemma returned a question-by-question response; Python validated question mapping and mark limits.")
                status.update(label="Gemma evaluation ready for teacher review", state="complete")
            else:
                st.write("Using the labeled deterministic demo response. No model request is made.")
                result = _demo_result(scheme, details["student_name"])
                model_name = "DEMO · deterministic sample"
                status.update(label="Demonstration result prepared", state="complete")
        with session_scope() as session:
            teacher = session.get(Teacher, owner_id)
            if teacher is None:
                raise RuntimeError("Teacher workspace was not initialized. Refresh and try again.")
            student = None
            if details["student_id"]:
                student = session.scalar(select(Student).where(Student.id == details["student_id"], Student.teacher_id == teacher.id))
                if student is None or student.is_demo != demo:
                    raise ValueError("The selected student record is no longer available in this workspace.")
            elif details["student_code"]:
                student = session.scalar(select(Student).where(Student.teacher_id == teacher.id, Student.student_code == details["student_code"]))
                if student is not None:
                    if student.is_demo != demo:
                        raise ValueError("That student ID is already used in the other workspace. Use a different ID.")
                    if student.name.casefold() != details["student_name"].casefold():
                        raise ValueError("That student ID belongs to a different student.")
            if student is None:
                student = Student(teacher_id=teacher.id, student_code=details["student_code"], name=details["student_name"], class_grade=details["class_grade"], is_demo=demo)
                session.add(student)
                session.flush()
            exam = Examination(teacher_id=teacher.id, title=details["title"], subject=details["subject"], class_grade=details["class_grade"], academic_year=details["academic_year"], exam_date=date.fromisoformat(details["exam_date"]), total_marks=details["total_marks"], is_demo=demo)
            for question in scheme.questions:
                exam.questions.append(Question(number=question.number, prompt=question.prompt, expected_answer=question.expected_answer, max_marks=question.max_marks, key_concepts=question.key_concepts, alternatives=question.alternatives, criteria=question.criteria, teacher_notes=question.teacher_notes))
            session.add(exam)
            session.flush()
            # Ensure the AI output cannot bypass the same deterministic checks used in live inference.
            from services.grading_service import validate_result
            validate_result(result, scheme)
            saved = save_evaluation(session, teacher.id, student, exam, scheme, result, draft["pages"], demo, model_name)
            st.session_state.selected_evaluation_id = saved.id
            st.session_state.last_evaluation_mode = "demo" if demo else "live"
        st.session_state.evaluation_draft = {"step": 1, "pages": [], "details": None, "scheme": None}
        st.session_state.pop("scheme_editor", None)
        for key in DETAIL_WIDGET_KEYS:
            st.session_state.pop(key, None)
        st.session_state.pop("_evaluation_details_initialized", None)
        st.session_state.pop("_restore_evaluation_details", None)
        st.switch_page(st.session_state.page_objects["Evaluation Review"])
    except (GemmaUnavailable, ValueError, RuntimeError) as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"The evaluation could not be saved. Your draft is available for retry. {exc}")


def _step_review(draft: dict) -> None:
    details = draft["details"]
    try:
        raw_scheme = draft["scheme"]
        scheme = MarkingScheme.model_validate_json(raw_scheme) if isinstance(raw_scheme, str) else MarkingScheme.model_validate(raw_scheme)
        # Also upgrade drafts created before the JSON-to-object transition.
        draft["scheme"] = scheme.model_dump()
    except ValidationError as exc:
        messages = "; ".join(error["msg"] for error in exc.errors())
        st.error(f"Your marking scheme needs correction before grading: {messages}")
        if st.button("Edit marking scheme"):
            _jump(3)
        return
    except Exception as exc:
        st.error(f"Your marking scheme needs correction before grading: {exc}")
        if st.button("Edit marking scheme"):
            _jump(3)
        return
    st.markdown("#### Check details before grading")
    safe = lambda value: html.escape(str(value or ""))
    st.markdown(f"<div class='review-summary'><div><small>STUDENT</small><strong>{safe(details['student_name'])}</strong><span>{safe(details['student_code'] or 'No student ID')} · {safe(details['class_grade'])}</span></div><div><small>EXAMINATION</small><strong>{safe(details['title'])}</strong><span>{safe(details['subject'])} · {safe(details['academic_year'])}</span></div><div><small>MARKS</small><strong>{sum(q.max_marks for q in scheme.questions):g}</strong><span>{len(scheme.questions)} questions</span></div><div><small>ANSWER SHEET</small><strong>{len(draft['pages'])} pages</strong><span>Previewed and ordered</span></div></div>", unsafe_allow_html=True)
    with st.expander("Review marking scheme", expanded=True):
        st.dataframe([{ "Question": f"Q{q.number}", "Prompt": q.prompt, "Expected answer": q.expected_answer, "Marks": q.max_marks, "Key concepts": ", ".join(q.key_concepts)} for q in scheme.questions], hide_index=True, use_container_width=True)
    if st.session_state.workspace_mode == "demo" and settings.live_ready:
        st.info(f"DEMO WORKSPACE · Gemma grading is enabled with {settings.gemma_model}; records stay labeled as demo data.")
        button_text = "Start Gemma evaluation"
    elif st.session_state.workspace_mode == "demo":
        st.info("DEMO WORKSPACE · No GEMMA_API_KEY is configured, so this creates a labeled sample result. Add the key to grade uploaded handwriting with Gemma.")
        button_text = "Start demo evaluation"
    else:
        st.warning("Live Gemma provides grading recommendations. Review every score and approve only after your own check.")
        button_text = "Start Gemma evaluation"
    back, start = st.columns(2)
    with back:
        if st.button("Back to marking scheme", use_container_width=True):
            _jump(3)
    with start:
        if st.button(button_text, icon=":material/auto_awesome:", type="primary", use_container_width=True):
            _start(draft)


def render() -> None:
    _init_draft()
    draft = st.session_state.evaluation_draft
    page_header("New evaluation", "Set up an assessment, upload pages, and keep the teacher in control.", "ASSESSMENT WORKFLOW")
    _progress(draft["step"])
    if draft["step"] == 1:
        _step_details(draft)
    elif draft["step"] == 2:
        _step_upload(draft)
    elif draft["step"] == 3:
        _step_scheme(draft)
    else:
        _step_review(draft)

