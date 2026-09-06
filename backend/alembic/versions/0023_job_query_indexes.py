"""index job recovery and history queries

Revision ID: 0023_job_query_indexes
Revises: 0022_jobs_updated_at_index
Create Date: 2026-07-18
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023_job_query_indexes"
down_revision: Union[str, None] = "0022_jobs_updated_at_index"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_jobs_recoverable_created_at_id",
            "jobs",
            ["created_at", "id"],
            unique=False,
            postgresql_where=sa.text(
                "status IN ('pending', 'cancel_requested', 'running')"
            ),
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_jobs_user_updated_created_id",
            "jobs",
            ["user_id", "updated_at", "created_at", "id"],
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_jobs_user_updated_created_id",
            table_name="jobs",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_jobs_recoverable_created_at_id",
            table_name="jobs",
            postgresql_concurrently=True,
            if_exists=True,
        )
