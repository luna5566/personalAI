"""persist document storage provenance

Revision ID: 0019_document_storage
Revises: 0018_storage_deletions
Create Date: 2026-07-18
"""

from typing import Union

from alembic import op
import sqlalchemy as sa

from app.core.config import settings
from app.storage.storage_service import current_storage_scope


revision: str = "0019_document_storage"
down_revision: Union[str, None] = "0018_storage_deletions"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("storage_backend", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("storage_scope", sa.Text(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE documents
            SET storage_backend = :storage_backend,
                storage_scope = :storage_scope
            WHERE file_path IS NOT NULL
            """
        ).bindparams(
            storage_backend=settings.storage_backend,
            storage_scope=current_storage_scope(),
        )
    )
    op.create_check_constraint(
        "ck_documents_file_storage_provenance",
        "documents",
        "(file_path IS NULL AND storage_backend IS NULL AND storage_scope IS NULL) "
        "OR (file_path IS NOT NULL AND storage_backend IS NOT NULL "
        "AND storage_scope IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_documents_file_storage_provenance",
        "documents",
        type_="check",
    )
    op.drop_column("documents", "storage_scope")
    op.drop_column("documents", "storage_backend")
