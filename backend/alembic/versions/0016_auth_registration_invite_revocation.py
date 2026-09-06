"""add registration invite revocation

Revision ID: 0016_invite_revocation
Revises: 0015_auth_registration_invites
Create Date: 2026-07-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016_invite_revocation"
down_revision: Union[str, None] = "0015_auth_registration_invites"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auth_registration_invites",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("auth_registration_invites", "revoked_at")
