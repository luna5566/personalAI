"""track the reconciled embedding configuration

Revision ID: 0021_embedding_config_state
Revises: 0020_storage_deletion_unique
Create Date: 2026-07-18
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021_embedding_config_state"
down_revision: Union[str, None] = "0020_storage_deletion_unique"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("configuration_fingerprint", sa.String(length=192), nullable=True),
    )
    op.create_index(
        "ix_jobs_configuration_fingerprint",
        "jobs",
        ["configuration_fingerprint"],
        unique=False,
    )
    op.create_table(
        "embedding_configuration_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=192), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "id = 1",
            name="ck_embedding_configuration_state_singleton",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("embedding_configuration_state")
    op.drop_index("ix_jobs_configuration_fingerprint", table_name="jobs")
    op.drop_column("jobs", "configuration_fingerprint")
