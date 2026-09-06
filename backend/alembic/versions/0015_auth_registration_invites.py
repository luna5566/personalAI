"""add one-time registration invites

Revision ID: 0015_auth_registration_invites
Revises: 0014_auth_session_client_name
Create Date: 2026-07-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0015_auth_registration_invites"
down_revision: Union[str, None] = "0014_auth_session_client_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_registration_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "code_hash",
            name="uq_auth_registration_invites_code_hash",
        ),
    )
    op.create_index(
        "ix_auth_registration_invites_expires_at",
        "auth_registration_invites",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_registration_invites_expires_at",
        table_name="auth_registration_invites",
    )
    op.drop_table("auth_registration_invites")
