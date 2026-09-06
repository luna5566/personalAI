"""deduplicate storage deletion intents

Revision ID: 0020_storage_deletion_unique
Revises: 0019_document_storage
Create Date: 2026-07-18
"""

from typing import Union

from alembic import op


revision: str = "0020_storage_deletion_unique"
down_revision: Union[str, None] = "0019_document_storage"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM storage_deletions AS duplicate
        USING storage_deletions AS keeper
        WHERE duplicate.storage_backend = keeper.storage_backend
          AND duplicate.storage_scope = keeper.storage_scope
          AND duplicate.storage_key = keeper.storage_key
          AND (duplicate.created_at, duplicate.id)
              > (keeper.created_at, keeper.id)
        """
    )
    op.create_unique_constraint(
        "uq_storage_deletions_location_key",
        "storage_deletions",
        ["storage_backend", "storage_scope", "storage_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_storage_deletions_location_key",
        "storage_deletions",
        type_="unique",
    )
