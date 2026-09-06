"""add durable storage deletion outbox

Revision ID: 0018_storage_deletions
Revises: 0017_user_owner_fks
Create Date: 2026-07-18
"""

from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0018_storage_deletions"
down_revision: Union[str, None] = "0017_user_owner_fks"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.create_table(
        "storage_deletions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_backend", sa.String(length=32), nullable=False),
        sa.Column("storage_scope", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "lease_token",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_storage_deletions_attempts_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_storage_deletions_eligible",
        "storage_deletions",
        ["next_attempt_at", "lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_storage_deletions_eligible",
        table_name="storage_deletions",
    )
    op.drop_table("storage_deletions")
