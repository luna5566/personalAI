"""index chunk keyword search

Revision ID: 0026_chunk_search
Revises: 0025_trigram_search
Create Date: 2026-07-18
"""

from typing import Union

from alembic import op


revision: str = "0026_chunk_search"
down_revision: Union[str, None] = "0025_trigram_search"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_document_chunks_search_trgm
            ON document_chunks USING gin ((
                coalesce(content, '') || ' ' || coalesce(section_title, '')
            ) gin_trgm_ops)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_document_chunks_search_trgm",
            table_name="document_chunks",
            postgresql_concurrently=True,
            if_exists=True,
        )
