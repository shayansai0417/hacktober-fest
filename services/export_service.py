"""PDF and CSV exports for reviewed evaluations and class records."""

from __future__ import annotations

import html
from io import BytesIO

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config import settings
from database.models import Evaluation


def class_csv(rows: list[dict], *, teacher_id: int) -> bytes:
    if any(row.get("teacher_id") != teacher_id for row in rows):
        raise PermissionError("CSV export contains records outside the signed-in teacher workspace.")
    columns = ["Student", "Subject", "Examination", "Marks", "Maximum marks", "Percentage", "Approval status"]
    data = [{"Student": r["student"], "Subject": r["subject"], "Examination": r["examination"], "Marks": r["score"], "Maximum marks": r["maximum"], "Percentage": r["percent"], "Approval status": r["status"]} for r in rows]
    return pd.DataFrame(data, columns=columns).to_csv(index=False).encode("utf-8-sig")


def evaluation_pdf(evaluation: Evaluation, *, teacher_id: int, institution: str | None = None) -> bytes:
    if evaluation.teacher_id != teacher_id:
        raise PermissionError("PDF export is limited to the signed-in teacher's evaluations.")
    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=letter, rightMargin=0.68 * inch, leftMargin=0.68 * inch, topMargin=0.65 * inch, bottomMargin=0.7 * inch, title=f"{evaluation.student.name} · {evaluation.examination.title}")
    styles = getSampleStyleSheet()
    ink, indigo, muted, line = colors.HexColor("#172033"), colors.HexColor("#4F46E5"), colors.HexColor("#64748B"), colors.HexColor("#E5E7EB")
    title = ParagraphStyle("BrandTitle", parent=styles["Title"], textColor=ink, fontName="Helvetica-Bold", fontSize=19, leading=24, spaceAfter=4)
    body = ParagraphStyle("BodySmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=9, leading=13, textColor=ink)
    small = ParagraphStyle("MutedSmall", parent=body, textColor=muted, fontSize=8, leading=11)
    story = [Paragraph("PAPERGRADE <font color='#4F46E5'>AI</font>", title), Paragraph("INTELLIGENT ASSESSMENT · FAIRER GRADING", small), Spacer(1, 18)]
    safe = lambda value: html.escape(str(value or ""))
    story.extend([Paragraph(safe(evaluation.student.name), styles["Heading1"]), Paragraph(f"{safe(institution or settings.institution)} · {safe(evaluation.student.class_grade or evaluation.examination.class_grade)}", small), Spacer(1, 8)])
    summary = [["EXAMINATION", "SUBJECT", "FINAL SCORE", "STATUS"], [safe(evaluation.examination.title), safe(evaluation.examination.subject), f"{evaluation.total_obtained:g} / {evaluation.examination.total_marks:g} ({evaluation.percent:.1f}%)", safe(evaluation.status.replace("_", " ").upper())]]
    table = Table(summary, colWidths=[2.15 * inch, 1.35 * inch, 1.8 * inch, 1.25 * inch])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F7F8FC")), ("TEXTCOLOR", (0, 0), (-1, 0), muted), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 10), ("LINEBELOW", (0, 0), (-1, -1), .5, line), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([table, Spacer(1, 18), Paragraph("QUESTION BREAKDOWN", styles["Heading2"])])
    for result in evaluation.question_results:
        story.extend([Paragraph(f"Q{result.question_number} · {result.final_marks:g} / {result.max_marks:g}", styles["Heading3"]), Paragraph(safe(result.question_text), body), Paragraph(f"<b>Answer read:</b> {safe(result.extracted_answer or 'No answer detected')}", body), Paragraph(f"<b>Expected:</b> {safe(result.expected_answer or '—')}", body), Paragraph(f"<b>Evaluation:</b> {safe(result.rationale or result.feedback or '—')}", body), Paragraph(f"<b>Feedback:</b> {safe(result.feedback or '—')}", body), Spacer(1, 9)])
    teacher_feedback = evaluation.teacher_feedback if evaluation.teacher_feedback is not None else evaluation.overall_feedback
    story.extend([Spacer(1, 6), Paragraph("TEACHER FEEDBACK", styles["Heading2"]), Paragraph(safe(teacher_feedback or "No teacher feedback supplied."), body)])
    if evaluation.overall_feedback and evaluation.overall_feedback.strip() != (teacher_feedback or "").strip():
        story.extend([Spacer(1, 6), Paragraph("ORIGINAL AI FEEDBACK SUGGESTION", styles["Heading3"]), Paragraph(safe(evaluation.overall_feedback), body)])
    story.extend([Spacer(1, 10), Paragraph(f"Approval status: {safe(evaluation.status.replace('_', ' ').title())} · Approved {safe(evaluation.approved_at.strftime('%d %b %Y') if evaluation.approved_at else 'not yet')}", small)])
    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(line)
        canvas.line(.68 * inch, .55 * inch, 7.82 * inch, .55 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(muted)
        canvas.drawString(.68 * inch, .36 * inch, "PAPERGRADE AI · Teacher-reviewed assessment")
        canvas.drawRightString(7.82 * inch, .36 * inch, f"Page {_doc.page}")
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()

