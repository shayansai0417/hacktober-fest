# PaperGrade AI

**Intelligent Assessment. Fairer Grading.**

PaperGrade AI is a teacher-controlled assessment workspace for handwritten answer sheets. It turns page images into a reviewable, question-by-question grading recommendation using Google's **Gemma 4** model. Teachers can correct marks and feedback, inspect the original page, and approve the final record.

The app has two clearly separated workspaces:

- **Demonstration mode** loads labeled sample students, exams, analytics, and a handwritten sample page. When `GEMMA_API_KEY` is configured, new demo evaluations and marking-scheme extraction can use Gemma; uploaded pages are sent to the configured model only when the teacher starts an AI action. Without a key, demo grading uses repeatable sample results.
- **Live Gemma mode** sends the uploaded page images and teacher-reviewed rubric to the configured Gemma model. The score remains a recommendation until the teacher reviews and approves it.

## Run locally

Python 3.12 or newer is recommended. On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python scripts/migrate_existing.py
streamlit run app.py
```

Open the local URL printed by Streamlit. With the default `.env.example`, a labeled demo account is available without a Gemma API key:

```text
Email: demo@papergrade.ai
Password: DemoPaperGrade2026!
```

The sign-in screen also has a one-click **Continue as demo teacher** option. The demo account is local/example-only and read-only for account credentials. If `GEMMA_API_KEY` is configured, the teacher can choose Gemma grading and rubric extraction in the demo workspace; uploaded files are sent only when those actions are started. Set `DEMO_LOGIN_ENABLED=false` to hide demo login; it is automatically disabled when `APP_ENV=production`. The first database migration creates the local schema, upload directory, and labeled demo records. Existing SQLite data is preserved.

Local development can leave `APP_SECRET_KEY` blank; PaperGrade generates an in-process key for verification and recovery token hashing. Production must provide a random secret of at least 32 bytes. Stop any running Streamlit process before migrating an existing SQLite file, then restart it after the migration finishes.

## Activate Live Gemma grading

1. Create a Google AI Studio API key with access to the Gemini API's hosted Gemma models.
2. Put the key in `.env` as `GEMMA_API_KEY=...` (or set the environment variable in your deployment).
3. Keep `GEMMA_MODEL=gemma-4-26b-a4b-it` unless you intentionally configure another Gemma model.
4. Restart Streamlit and select **Live Gemma mode** in the left sidebar.

The app calls `client.models.generate_content` with the configured Gemma model and sends each normalized answer page as an image part. PDFs are rendered to page images before inference. The model response is validated with Pydantic and deterministic Python checks for question mapping and maximum marks. Transient API failures receive one bounded retry; malformed output is returned for teacher recovery and is never approved automatically. No Gemini, OpenAI, Claude, or OCR substitution is made.

The Google GenAI Python SDK communicates with Google's hosted API, so live grading requires internet access and an enabled API key. A quota or access denial is reported to the teacher, and the saved draft remains available for retry.

## What is implemented

- Dashboard with assessment metrics, subject averages, score bands, and recent work.
- Four-step evaluation setup for examination details, students, images/PDFs, editable marking schemes, and a final confirmation before grading.
- Multi-page PDF rendering, image validation, EXIF orientation correction, page previews, page ordering/removal, upload limits, and persistent upload paths.
- Teacher-editable question rubrics and optional Gemma extraction from uploaded scheme pages in Live mode.
- Actual multimodal Gemma inference, structured response validation, partial-mark recommendations, review flags, and a deterministic labeled demo path.
- Review screen with original answer pages, per-question explanations, suggested and teacher-adjusted marks, feedback, private notes, revision history, restored suggestions, running score totals, and explicit approval/reopen actions.
- Searchable history, filtered class CSV exports, branded individual PDF reports, student management, stored-record analytics, and profile/system settings.
- Teacher signup, sign-in, logout, expiring server-side sessions, password hashing, rate-limited login, single-use password reset and email verification links, plus account deletion.
- Independent teacher workspaces. Student, exam, evaluation, analytics, review, and report queries are scoped to the authenticated teacher; nested questions, uploaded pages, feedback, and revisions are reached only through an owned exam/evaluation.
- A local demonstration login with isolated, labeled fixtures. Production disables it by default.
- SQLAlchemy persistence on SQLite or PostgreSQL, a teacher-scoped data model, Alembic migration scaffolding, Docker, and a Render blueprint with a persistent disk.

## Architecture

```text
app.py / pages/             Streamlit shell and teacher workflows
components/                 Sidebar navigation and shared presentation
services/gemma_service.py   Image requests to the configured Gemma model
services/grading_service.py Pydantic-adjacent business invariants and score rules
services/evaluation_service.py Persistence, edit history, and approval transitions
services/analytics_service.py Analytics computed from stored evaluation records
services/export_service.py  ReportLab PDF and Pandas CSV output
database/models.py          SQLAlchemy relationships and teacher-owned records
database/db.py              SQLite/PostgreSQL engine and session handling
schemas.py                  Pydantic schemas for marking schemes and AI responses
utils/                      Safe file validation, PDF conversion, and image normalization
sample_data/                Clearly identified demo rubric, response, and handwritten page
tests/                      Database, grading, file, Gemma-mock, export, and app checks
```

Legacy records remain attached to their existing teacher row. The authentication migration flags pre-auth teacher rows as `is_legacy_owner=true` and leaves their password unset; they cannot sign in until an administrator assigns access. No assessment data is deleted or reassigned to a new signup. If two legacy rows had case-insensitive duplicate emails, the later row receives an `@unclaimed.invalid` address so future signups can enforce unique emails; the row and all owned work remain intact for manual assignment.

## Configuration

| Variable | Purpose | Local default |
| --- | --- | --- |
| `APP_ENV` | Environment label | `development` |
| `APP_SECRET_KEY` | Secret pepper for one-time auth tokens and email lookup throttles | generated for local process; required in production |
| `DEMO_MODE` | Initial sidebar mode | `true` |
| `DEMO_LOGIN_ENABLED` | Show the local example login | `true` locally; forced off in production |
| `DEMO_LOGIN_EMAIL` | Example account email | `demo@papergrade.ai` |
| `DEMO_LOGIN_PASSWORD` | Example account password | `DemoPaperGrade2026!` locally; never deployed |
| `REQUIRE_EMAIL_VERIFICATION` | Require verification before sign-in | `false` locally; `true` in production |
| `PUBLIC_APP_URL` | Base URL for verification and reset links | `http://localhost:8501` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` | SMTP delivery for verification and recovery | unset locally |
| `GEMMA_API_KEY` | Google AI Studio API key (secret) | empty |
| `GEMMA_MODEL` | Gemma model id | `gemma-4-26b-a4b-it` |
| `DATABASE_URL` | SQLAlchemy URL | SQLite `papergrade.db` |
| `UPLOAD_DIR` | Persistent processed page storage | `storage/uploads` |
| `MAX_UPLOAD_MB` | Per-file limit | `20` |
| `GEMMA_TIMEOUT_SECONDS` | Request timeout | `300` |
| `GEMMA_IMAGE_BATCH_SIZE` | Images per Gemma call for long answer sheets | `6` |
| `TEACHER_NAME` | First-run profile name | `Maya Patel` |
| `INSTITUTION` | First-run/report institution | `Northstar Learning Centre` |
| `TEACHER_EMAIL` | First-run profile email | `maya@example.edu` |

The app never writes API keys to the database or shows the key in the UI. Uploaded answer sheets are excluded by `.gitignore`; configure a persistent upload location before grading real student papers. The demo handwriting page is a deliberately published sample asset.

Streamlit also enforces an upload limit in `.streamlit/config.toml` before the app receives a file. Set `STREAMLIT_SERVER_MAXUPLOADSIZE` to the same value as `MAX_UPLOAD_MB` when increasing that limit.

## Database and migrations

For local first-run setup, `python scripts/migrate_existing.py` creates the schema. `DATABASE_URL` may use SQLite locally or PostgreSQL. Production startup requires PostgreSQL, an `APP_SECRET_KEY`, and SMTP configured for account verification and recovery. Production app startup does not alter the schema; the deployment command applies migrations first.

Alembic configuration is included. After changing the ORM schema, create and review a migration, then apply it before starting the new app version:

```bash
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
```

`scripts/migrate_existing.py` safely handles a fresh database, an older `create_all()` database without migration history, and a database already initialized by the current ORM. It stamps the matching baseline where appropriate, then applies outstanding migrations. It stops instead of guessing when it finds a partially initialized schema. Back up production before migration. Existing teacher records and their owned data remain in place.

## Deployment

### Docker

```bash
docker build -t papergrade-ai .
docker run --rm -p 8501:8501 \
  -e GEMMA_API_KEY="$GEMMA_API_KEY" \
  -e DATABASE_URL="sqlite:////var/data/papergrade.db" \
  -v papergrade-data:/var/data papergrade-ai
```

Set `UPLOAD_DIR=/var/data/uploads` when starting the container. Use PostgreSQL for production; SQLite remains supported for local development.

### Render

The included `render.yaml` defines a Streamlit service, managed PostgreSQL, and a persistent disk for uploaded pages. Connect the repository to Render and apply the Blueprint. Supply `GEMMA_API_KEY` and the SMTP host, username, password, and from-address when prompted. Render generates `APP_SECRET_KEY`; production verification links use `RENDER_EXTERNAL_URL` unless `PUBLIC_APP_URL` is set. Demo login and demo grading data are disabled in production. Legacy pre-auth accounts require an administrator to assign new login credentials; their existing records remain preserved under their original teacher row.

## Test and verify

```bash
pytest -q
```

Tests mock Gemma and email delivery and do not use a paid API. The optional live integration check is `tests/test_gemma_live.py`; it is skipped unless `RUN_LIVE_GEMMA_TEST=1` and `GEMMA_API_KEY` are set. Do not put student data into test fixtures.

## Fair grading and data handling

The marking scheme is the grading authority. The app checks mark bounds, total arithmetic, and missing/duplicate question mappings in Python. Unclear handwriting and low confidence create review flags. The teacher can edit marks and feedback, inspect the submitted page, and approve only after clearing outstanding review flags. Evaluation changes are audited while preserving the initial AI suggestion. This workflow supports consistency but does not claim perfect or objective fairness; teachers remain responsible for the final decision.

