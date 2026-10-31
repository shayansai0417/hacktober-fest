"""add teacher authentication, verification and rate-limit storage

Revision ID: 0003_teacher_auth
Revises: 0002_teacher_feedback
Create Date: 2026-10-31
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_teacher_auth"
down_revision = "0002_teacher_feedback"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("teachers")}
    additions = [
        ("password_hash", sa.Column("password_hash", sa.Text(), nullable=True)),
        ("session_version", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0")),
        ("designation", sa.Column("designation", sa.String(120), nullable=False, server_default="")),
        ("subject_specialization", sa.Column("subject_specialization", sa.String(180), nullable=False, server_default="")),
        ("email_verified", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("email_verified_at", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)),
        ("is_demo_account", sa.Column("is_demo_account", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("is_legacy_owner", sa.Column("is_legacy_owner", sa.Boolean(), nullable=False, server_default=sa.false())),
    ]
    for name, column in additions:
        if name not in columns:
            op.add_column("teachers", column)

    # Keep every pre-auth teacher and all child rows intact. Existing owners have
    # no password and are explicitly flagged for a controlled manual assignment.
    op.execute(sa.text("UPDATE teachers SET is_legacy_owner = TRUE, email_verified = TRUE WHERE password_hash IS NULL AND is_demo_account = FALSE"))
    rows = bind.execute(sa.text("SELECT id, email FROM teachers ORDER BY id")).all()
    used: set[str] = set()
    for row in rows:
        normalized = (row.email or "").strip().casefold()
        if normalized and normalized in used:
            normalized = f"legacy-{row.id}@unclaimed.invalid"
            bind.execute(sa.text("UPDATE teachers SET email = :email WHERE id = :id"), {"email": normalized, "id": row.id})
        elif normalized:
            bind.execute(sa.text("UPDATE teachers SET email = :email WHERE id = :id"), {"email": normalized, "id": row.id})
        if normalized:
            used.add(normalized)

    for name, columns, unique, options in (
        ("ix_teachers_is_demo_account", ["is_demo_account"], False, {}),
        ("ix_teachers_is_legacy_owner", ["is_legacy_owner"], False, {}),
        ("uq_teachers_email_lower", [sa.text("lower(email)")], True, {
            "sqlite_where": sa.text("email <> ''"), "postgresql_where": sa.text("email <> ''"),
        }),
    ):
        if name not in {index["name"] for index in sa.inspect(bind).get_indexes("teachers")}:
            op.create_index(name, "teachers", columns, unique=unique, **options)

    if "auth_tokens" not in sa.inspect(bind).get_table_names():
        op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        )
    token_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("auth_tokens")}
    for name, column in (("ix_auth_tokens_teacher_id", "teacher_id"), ("ix_auth_tokens_purpose", "purpose"), ("ix_auth_tokens_expires_at", "expires_at")):
        if name not in token_indexes:
            op.create_index(name, "auth_tokens", [column])

    if "login_throttles" not in sa.inspect(bind).get_table_names():
        op.create_table(
        "login_throttles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email_hash", sa.String(64), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email_hash"),
        )


def downgrade():
    op.drop_table("login_throttles")
    op.drop_index("ix_auth_tokens_expires_at", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_purpose", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_teacher_id", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_index("uq_teachers_email_lower", table_name="teachers")
    op.drop_index("ix_teachers_is_legacy_owner", table_name="teachers")
    op.drop_index("ix_teachers_is_demo_account", table_name="teachers")
    for column in ("is_legacy_owner", "is_demo_account", "email_verified_at", "email_verified", "subject_specialization", "designation", "session_version", "password_hash"):
        op.drop_column("teachers", column)
