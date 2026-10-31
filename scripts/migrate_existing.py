"""Safely migrate fresh, legacy, and previously auto-initialized PaperGrade DBs."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from config import settings


BASELINE_TABLES = {
    "teachers", "students", "examinations", "questions", "evaluations",
    "answer_sheets", "uploaded_pages", "question_evaluations",
    "teacher_revisions", "activity_logs",
}
AUTH_COLUMNS = {
    "password_hash", "session_version", "designation", "subject_specialization",
    "email_verified", "email_verified_at", "is_demo_account", "is_legacy_owner",
}


def _database_url() -> str:
    url = settings.database_url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def _config() -> Config:
    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", _database_url().replace("%", "%%"))
    return config


def migrate() -> None:
    settings.validate_production_configuration()
    config = _config()
    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        if "alembic_version" not in tables and tables:
            if "teachers" not in tables or not BASELINE_TABLES.issubset(tables):
                raise RuntimeError(
                    "The existing database is only partially initialized. No migration was run; "
                    "restore the last backup or repair the missing tables first."
                )
            teacher_columns = {column["name"] for column in inspector.get_columns("teachers")}
            if AUTH_COLUMNS.issubset(teacher_columns) and {"auth_tokens", "login_throttles", "auth_sessions"}.issubset(tables):
                # Earlier app startup used SQLAlchemy create_all plus additive local
                # columns. Record that already-applied schema without replaying DDL.
                command.stamp(config, "head")
            else:
                # Mark the pre-auth schema as the baseline; the next revisions add
                # teacher feedback (if needed) and authentication without replacing data.
                command.stamp(config, "0001_initial")
        command.upgrade(config, "head")
    finally:
        engine.dispose()


if __name__ == "__main__":
    migrate()
    print("PaperGrade AI database is at the latest migration revision.")
