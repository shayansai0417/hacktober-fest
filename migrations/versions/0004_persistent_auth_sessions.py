"""persist revocable login sessions for browser reloads and remember-me

Revision ID: 0004_auth_sessions
Revises: 0003_teacher_auth
Create Date: 2026-10-31
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_auth_sessions"
down_revision = "0003_teacher_auth"
branch_labels = None
depends_on = None


def upgrade():
    if "auth_sessions" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("teacher_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("session_version", sa.Integer(), nullable=False),
            sa.Column("remember", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("auth_sessions")}
    if "ix_auth_sessions_teacher_id" not in indexes:
        op.create_index("ix_auth_sessions_teacher_id", "auth_sessions", ["teacher_id"])
    if "ix_auth_sessions_expires_at" not in indexes:
        op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade():
    op.drop_table("auth_sessions")
