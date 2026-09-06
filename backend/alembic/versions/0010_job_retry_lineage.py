"""add job retry lineage

Revision ID: 0010_job_retry_lineage
Revises: 0009_vector_index
Create Date: 2026-07-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010_job_retry_lineage"
down_revision: Union[str, None] = "0009_vector_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("retry_of_job_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_jobs_retry_of_job_id", "jobs", ["retry_of_job_id"])
    op.create_foreign_key(
        "fk_jobs_retry_of_job_id_jobs",
        "jobs",
        "jobs",
        ["retry_of_job_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_jobs_retry_of_job_id_jobs",
        "jobs",
        type_="foreignkey",
    )
    op.drop_index("ix_jobs_retry_of_job_id", table_name="jobs")
    op.drop_column("jobs", "retry_of_job_id")
