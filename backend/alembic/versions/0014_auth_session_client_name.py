"""add authentication session client name

Revision ID: 0014_auth_session_client_name
Revises: 0013_auth_sessions
Create Date: 2026-07-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014_auth_session_client_name"
down_revision: Union[str, None] = "0013_auth_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("client_name", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("auth_sessions", "client_name")
