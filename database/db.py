"""Database engine, session factory, and first-run initialization."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from config import settings
from database.models import Base


url = settings.database_url
if url.startswith("postgres://"):
    url = "postgresql+psycopg://" + url.removeprefix("postgres://")
elif url.startswith("postgresql://") and "+" not in url.split(":", 1)[0]:
    url = "postgresql+psycopg://" + url.removeprefix("postgresql://")

engine = create_engine(url, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})

if url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    if settings.is_production:
        # Production schema changes are applied by the explicit Alembic step in
        # the deployment command. Never mutate tenant tables during app startup.
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        if revision != "0004_auth_sessions":
            raise RuntimeError("Database schema is not current. Run scripts/migrate_existing.py before starting the app.")
        return
    Base.metadata.create_all(bind=engine)
    # create_all does not add columns to a database created by an older version.
    # Keep local Streamlit databases compatible with additive model changes.
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("evaluations")}
        if "teacher_feedback" not in columns:
            connection.execute(text("ALTER TABLE evaluations ADD COLUMN teacher_feedback TEXT"))
        teacher_columns = {column["name"] for column in inspect(connection).get_columns("teachers")}
        legacy_flag_missing = "is_legacy_owner" not in teacher_columns
        boolean_default = "FALSE" if connection.dialect.name == "postgresql" else "0"
        additions = {
            "password_hash": "TEXT",
            "session_version": "INTEGER NOT NULL DEFAULT 0",
            "designation": "VARCHAR(120) NOT NULL DEFAULT ''",
            "subject_specialization": "VARCHAR(180) NOT NULL DEFAULT ''",
            "email_verified": f"BOOLEAN NOT NULL DEFAULT {boolean_default}",
            "email_verified_at": "TIMESTAMP WITH TIME ZONE",
            "is_demo_account": f"BOOLEAN NOT NULL DEFAULT {boolean_default}",
            "is_legacy_owner": f"BOOLEAN NOT NULL DEFAULT {boolean_default}",
        }
        for name, definition in additions.items():
            if name not in teacher_columns:
                connection.execute(text(f"ALTER TABLE teachers ADD COLUMN {name} {definition}"))
        if legacy_flag_missing:
            connection.execute(text("UPDATE teachers SET is_legacy_owner = TRUE WHERE password_hash IS NULL AND is_demo_account = FALSE"))
        # The database enforces case-insensitive uniqueness even when concurrent
        # signups race past the friendly validation check.
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_teachers_email_lower ON teachers (lower(email)) WHERE email <> ''"))


@contextmanager
def session_scope():
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

