"""Product landing page for the existing PaperGrade assessment workspace."""

from __future__ import annotations

import base64
import html

import streamlit as st

from config import ROOT_DIR
from pages._common import current_mode, rows_for_mode


def _request_demo_mode() -> None:
    """Let the app shell set the sidebar radio before it is instantiated."""
    st.session_state._pending_workspace_mode = "demo"


def _dashboard_preview(rows: list[dict], demo: bool) -> tuple[str, str]:
    count = len(rows)
    average = sum(row["percent"] for row in rows) / count if count else None
    pending = sum(row["status"] != "approved" for row in rows)
    average_note = f"Based on {count} saved assessment{'s' if count != 1 else ''}" if count else "No saved assessments yet"
    metrics = "".join(
        f"<div class='lp-stat'><span>{label}</span><strong>{value}</strong><small>{note}</small></div>"
        for label, value, note in [
            ("EVALUATIONS", str(count) if count else "—", "Saved assessments"),
            ("CLASS AVERAGE", f"{average:.1f}%" if average is not None else "—", average_note),
            ("PENDING REVIEW", str(pending) if count else "—", "Teacher approval"),
        ]
    )

    subject_values: dict[str, list[float]] = {}
    for row in rows:
        subject_values.setdefault(row["subject"], []).append(float(row["percent"]))
    subject_averages = sorted(
        ((name, sum(scores) / len(scores)) for name, scores in subject_values.items()),
        key=lambda item: item[1],
        reverse=True,
    )[:4]
    chart = "".join(
        f"<div class='lp-bar'><i style='height:{max(5, min(score, 100)):.0f}%'></i><span>{html.escape(name[:12])}</span></div>"
        for name, score in subject_averages
    ) or "<div class='lp-empty-chart'>Saved subject averages appear here.</div>"

    recent_rows = "".join(
        "<div class='lp-table-row'>"
        f"<span><b>{html.escape(row['student'])}</b><small>{html.escape(row['subject'])}</small></span>"
        f"<span>{html.escape(row['examination'])}</span>"
        f"<b>{row['score']:g} / {row['maximum']:g}</b>"
        f"<i class='lp-status {'approved' if row['status'] == 'approved' else 'review'}'>{html.escape(row['status'].replace('_', ' ').title())}</i>"
        "</div>"
        for row in rows[:3]
    ) or "<div class='lp-table-empty'>No evaluations saved yet. Start an assessment to see it here.</div>"

    scope = "SAMPLE DEMO DATA" if demo else "YOUR WORKSPACE"
    markup = f"""
    <div class="lp-dashboard-wrap">
      <div class="lp-window">
        <div class="lp-windowbar"><span class="lp-window-dots"><i></i><i></i><i></i></span><span>ASSESSMENT OVERVIEW</span><b>{scope}</b></div>
        <div class="lp-dashboard-body">
          <div class="lp-dash-heading"><div><small>TEACHER WORKSPACE</small><strong>Good morning, Teacher.</strong><span>Your assessment overview</span></div><a href="/new-evaluation">+ New evaluation</a></div>
          <div class="lp-stats">{metrics}</div>
          <div class="lp-dash-grid">
            <div class="lp-panel lp-chart"><div class="lp-panel-title"><b>Average score by subject</b><span>Based on saved records</span></div><div class="lp-bars">{chart}</div></div>
            <div class="lp-panel lp-recent"><div class="lp-panel-title"><b>Recent evaluations</b><a href="/history">View all</a></div><div class="lp-table-head"><span>STUDENT</span><span>ASSESSMENT</span><span>SCORE</span><span>STATUS</span></div>{recent_rows}</div>
          </div>
          <div class="lp-data-note">{scope} · All figures are drawn from the selected workspace.</div>
        </div>
      </div>
    """
    # Close the dashboard wrapper; decorative cards are omitted so Streamlit's
    # Markdown parser cannot interpret their markup as a code block.
    markup = markup.rstrip() + "</div>"
    return markup, scope


def _feature_cards() -> str:
    features = [
        ("01", "Handwriting recognition", "Read handwritten responses from uploaded image pages and PDFs."),
        ("02", "Question-wise evaluation", "Compare each answer with the teacher’s marking scheme."),
        ("03", "Custom marking schemes", "Upload a rubric or enter its questions, marks, and criteria."),
        ("04", "Explainable suggestions", "Review the reasoning and concepts behind suggested marks."),
        ("05", "Teacher approval", "Edit marks and feedback. Final approval always stays with the teacher."),
        ("06", "Assessment analytics", "Explore score distributions, subject averages, and question trends."),
        ("07", "Multi-page PDFs", "Process complete answer sheets as ordered page images."),
        ("08", "Exportable reports", "Download individual assessment reports and class records."),
    ]
    return "".join(
        f"<article class='lp-feature'><span>{number}</span><div><h3>{title}</h3><p>{description}</p></div><i>↗</i></article>"
        for number, title, description in features
    )


def render() -> None:
    demo = current_mode()
    rows = rows_for_mode()
    preview, scope = _dashboard_preview(rows, demo)
    sample_path = ROOT_DIR / "sample_data" / "demo_answer_sheet.png"
    image_data = base64.b64encode(sample_path.read_bytes()).decode("ascii") if sample_path.exists() else ""
    answer_image = (
        f"<img src='data:image/png;base64,{image_data}' alt='Illustrative handwritten answer sheet'>"
        if image_data
        else "<div class='lp-paper-placeholder'>Handwritten answer sheet preview</div>"
    )

    st.markdown("""
    <nav class="lp-nav" aria-label="Main navigation">
      <a class="lp-brand" href="#top"><span class="lp-brand-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4.5h14v15H5z"/><path d="M8.5 8h7M8.5 11.5h7M8.5 15h4"/><path d="m15.5 16 1.5 1.5 3-3"/></svg></span><span>PaperGrade <b>AI</b><small>ASSESSMENT WORKSPACE</small></span></a>
      <div class="lp-nav-links"><a href="#product">Product</a><a href="#how-it-works">How it works</a><a href="#features">Features</a><a href="#about">About</a></div>
      <div class="lp-nav-actions"><a class="lp-nav-workspace" href="/dashboard">Workspace</a><a class="lp-nav-cta" href="/new-evaluation">Get started <span>↗</span></a></div>
      <details class="lp-mobile-menu"><summary aria-label="Open navigation">☰</summary><div><a href="#product">Product</a><a href="#how-it-works">How it works</a><a href="#features">Features</a><a href="#about">About</a><a href="/dashboard">Workspace</a><a href="/new-evaluation">Get started ↗</a></div></details>
    </nav>
    <div id="top" class="lp-anchor"></div>
    """, unsafe_allow_html=True)

    left, right = st.columns([0.91, 1.09], gap="large")
    with left:
        st.markdown("""
        <div class="lp-hero-copy">
          <div class="lp-eyebrow"><span></span> INTELLIGENT ASSESSMENT <i>·</i> FAIRER GRADING</div>
          <h1>Spend less time grading.<br><em>More time teaching.</em></h1>
          <p>Read handwritten answers, evaluate against your marking scheme, and keep every final mark in your hands.</p>
        </div>
        """, unsafe_allow_html=True)
        with st.container(key="landing_hero_actions"):
            actions = st.columns([1.12, 1], gap="small")
            with actions[0]:
                if st.button("Start grading", key="landing_start_grading", type="primary", icon=":material/arrow_forward:", use_container_width=True):
                    st.switch_page(st.session_state.page_objects["New Evaluation"])
            with actions[1]:
                if st.button("Explore demo", key="landing_explore_demo", icon=":material/visibility:", use_container_width=True, on_click=_request_demo_mode):
                    st.switch_page(st.session_state.page_objects["Dashboard"])
        st.markdown("""
        <div class="lp-trust"><span><i>✓</i> Teacher reviewed</span><span><i>✓</i> Rubric led</span><span><i>✓</i> AI assisted</span></div>
        <div class="lp-hero-footnote">A teacher-controlled workflow, from upload through approval.</div>
        """, unsafe_allow_html=True)
    with right:
        st.markdown(f"<div class='lp-hero-visual'>{preview}</div>", unsafe_allow_html=True)

    st.markdown("""
    <section class="lp-workflow lp-section" id="how-it-works">
      <div class="lp-section-head"><div><span class="lp-section-kicker">A CLEAR, TEACHER-LED WORKFLOW</span><h2>From the first page to the final mark.</h2></div><p>PaperGrade keeps the source material, rubric, and teacher review connected in one assessment record.</p></div>
      <div class="lp-steps">
        <article><span class="lp-step-num">01</span><div class="lp-step-art upload-art"><div class="lp-art-page"><i>PDF</i><span>answer-sheet.pdf</span><b>↑</b></div><small>PDF · JPG · PNG</small></div><h3>Upload answer sheets</h3><p>Add scanned handwriting or a multi-page PDF, preview every page, and arrange the order.</p></article>
        <article><span class="lp-step-num">02</span><div class="lp-step-art rubric-art"><div class="lp-rubric-line"><b>Q1</b><span>Method and reasoning</span><i>5 marks</i></div><div class="lp-rubric-line"><b>Q2</b><span>Working and answer</span><i>10 marks</i></div><div class="lp-rubric-check">Rubric matched <span>✓</span></div></div><h3>AI evaluates by rubric</h3><p>Gemma reads each answer and suggests question-level marks with a reason and review flags.</p></article>
        <article><span class="lp-step-num">03</span><div class="lp-step-art approve-art"><div class="lp-score-row"><span>Suggested score</span><b>24 <i>/ 27</i></b></div><div class="lp-review-chip"><span></span> Teacher review</div><div class="lp-approve-line">Final approval stays with you <b>✓</b></div></div><h3>Review and approve</h3><p>Edit marks and student feedback, resolve uncertain answers, then approve and export the report.</p></article>
      </div>
    </section>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <section class="lp-product lp-section" id="product">
      <div class="lp-section-head lp-product-head"><div><span class="lp-section-kicker">PRODUCT SHOWCASE · ILLUSTRATIVE DEMO</span><h2>From handwritten answers<br>to meaningful insights.</h2></div><p>A sample review screen to show how question-level suggestions and teacher edits work together. These marks are illustrative, not generated from your paper.</p></div>
      <div class="lp-showcase">
        <div class="lp-answer-panel"><div class="lp-showcase-bar"><span><i></i><i></i><i></i> ANSWER SHEET</span><b>PAGE 01 / 01</b></div><div class="lp-paper-stage">{answer_image}<span class="lp-highlight lp-highlight-one">Q1</span><span class="lp-highlight lp-highlight-two">Q2</span></div><div class="lp-paper-caption"><span>DEMO SAMPLE · handwritten answer page</span><span>Source page preview</span></div></div>
        <div class="lp-eval-panel"><div class="lp-eval-top"><div><span>QUESTION-WISE REVIEW</span><b>Illustrative Gemma suggestions</b></div><i>DEMO</i></div>
          <article class="lp-eval-question"><div><span>QUESTION 1 <small>MAX 5</small></span><b>4 <i>/ 5</i></b></div><h3>Wave interference</h3><p>Correct explanation of the concept. One important supporting point is missing.</p><div class="lp-feedback-meter"><i style="width:82%"></i></div><small>Confidence field is supported by the evaluation response.</small></article>
          <article class="lp-eval-question"><div><span>QUESTION 2 <small>MAX 10</small></span><b>8 <i>/ 10</i></b></div><h3>Numerical problem</h3><p>Good method and relevant working. A minor detail is missing from the final reasoning.</p><div class="lp-feedback-meter"><i style="width:76%"></i></div><small>Teacher can edit the score and student-facing feedback.</small></article>
          <div class="lp-rubric-match"><span>MARKING SCHEME</span><b>Method · key concepts · partial credit</b><i>Teacher remains final authority</i></div>
          <a class="lp-showcase-link" href="/new-evaluation">Try this workflow <span>↗</span></a>
        </div>
      </div>
      <div class="lp-showcase-note">DEMO RESULT · The sample page and suggestions above are illustrative and do not represent an AI evaluation of a visitor’s work.</div>
    </section>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <section class="lp-features lp-section" id="features">
      <div class="lp-section-head"><div><span class="lp-section-kicker">BUILT FOR REAL REVIEW</span><h2>Thoughtful tools for the work teachers do.</h2></div><p>Each capability connects to the existing PaperGrade assessment workflow.</p></div>
      <div class="lp-feature-grid">{_feature_cards()}</div>
    </section>
    """, unsafe_allow_html=True)

    st.markdown("""
    <section class="lp-about lp-section" id="about">
      <div class="lp-about-heading"><span class="lp-section-kicker">WHY PAPERGRADE AI</span><h2>Less repetitive checking.<br><em>More room for teaching.</em></h2><p>AI can help organize the grading work. Teachers retain the judgment, context, and final approval.</p></div>
      <div class="lp-compare"><div><span>TRADITIONAL WORKFLOW</span><h3>Scattered effort</h3><p><i>−</i> Repetitive manual checking</p><p><i>−</i> Mark calculations across pages</p><p><i>−</i> Performance tracked in separate places</p><p><i>−</i> Hard-to-revisit grading decisions</p></div><div class="lp-compare-divider">→</div><div class="lp-compare-product"><span>PAPERGRADE WORKSPACE</span><h3>One reviewed record</h3><p><i>✓</i> AI-assisted question review</p><p><i>✓</i> Rubric-guided suggestions</p><p><i>✓</i> Central assessment history</p><p><i>✓</i> Teacher-edited, teacher-approved results</p></div></div>
    </section>
    <footer class="lp-footer">
      <div class="lp-footer-brand"><a class="lp-brand" href="#top"><span class="lp-brand-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4.5h14v15H5z"/><path d="M8.5 8h7M8.5 11.5h7M8.5 15h4"/><path d="m15.5 16 1.5 1.5 3-3"/></svg></span><span>PaperGrade <b>AI</b><small>ASSESSMENT WORKSPACE</small></span></a><p>AI-assisted assessment, with final grading authority in teachers’ hands.</p></div>
      <div class="lp-footer-links"><b>PRODUCT</b><a href="#product">Showcase</a><a href="#how-it-works">How it works</a><a href="#features">Features</a><a href="/dashboard">Workspace</a></div>
      <div class="lp-footer-links"><b>GET STARTED</b><a href="/new-evaluation">New evaluation</a><a href="/history">Evaluation history</a><a href="/analytics">Analytics</a><span>Sign-in is not configured in this single-teacher workspace.</span></div>
      <div class="lp-footer-links"><b>CONTACT &amp; LEGAL</b><span>Contact details are not configured.</span><span>Privacy Policy: not configured by the deploying organization.</span><span>Terms of Service: not configured by the deploying organization.</span></div>
      <div class="lp-footer-legal"><span>© PaperGrade AI · Teacher-controlled assessment</span><span>Privacy and terms pages must be configured by the deploying organization.</span></div>
    </footer>
    """, unsafe_allow_html=True)
