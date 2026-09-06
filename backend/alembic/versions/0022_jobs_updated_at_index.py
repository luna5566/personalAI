"""index jobs for bounded history maintenance

Revision ID: 0022_jobs_updated_at_index
Revises: 0021_embedding_config_state
Create Date: 2026-07-18
"""

from typing import Union

from alembic import op


revision: str = "0022_jobs_updated_at_index"
down_revision: Union[str, None] = "0021_embedding_config_state"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_jobs_updated_at_id",
            "jobs",
            ["updated_at", "id"],
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_jobs_updated_at_id",
            table_name="jobs",
            postgresql_concurrently=True,
            if_exists=True,
        )
