"""store editable teacher feedback separately from the AI suggestion

Revision ID: 0002_teacher_feedback
Revises: 0001_initial
Create Date: 2026-10-31
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_teacher_feedback"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("evaluations")}
    if "teacher_feedback" not in columns:
        op.add_column("evaluations", sa.Column("teacher_feedback", sa.Text(), nullable=True))


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("evaluations")}
    if "teacher_feedback" in columns:
        op.drop_column("evaluations", "teacher_feedback")
