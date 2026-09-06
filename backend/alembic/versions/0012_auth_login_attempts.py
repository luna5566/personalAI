"""add shared login attempt limits

Revision ID: 0012_auth_login_attempts
Revises: 0011_job_run_token
Create Date: 2026-07-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_auth_login_attempts"
down_revision: Union[str, None] = "0011_job_run_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_login_attempts",
        sa.Column("scope_hash", sa.String(length=64), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "failed_attempts >= 0",
            name="ck_auth_login_attempts_failed_attempts_nonnegative",
        ),
        sa.PrimaryKeyConstraint("scope_hash"),
    )
    op.create_index(
        "ix_auth_login_attempts_updated_at",
        "auth_login_attempts",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_login_attempts_updated_at",
        table_name="auth_login_attempts",
    )
    op.drop_table("auth_login_attempts")
