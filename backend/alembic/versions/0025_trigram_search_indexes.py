"""add trigram search indexes

Revision ID: 0025_trigram_search
Revises: 0024_stable_pagination
Create Date: 2026-07-18
"""

from typing import Union

from alembic import op


revision: str = "0025_trigram_search"
down_revision: Union[str, None] = "0024_stable_pagination"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_documents_search_trgm
            ON documents USING gin ((
                coalesce(title, '') || ' ' ||
                coalesce(raw_text, '') || ' ' ||
                coalesce(cleaned_text, '') || ' ' ||
                coalesce(summary, '')
            ) gin_trgm_ops)
            """
        )
        op.create_index(
            "ix_conversations_title_trgm",
            "conversations",
            ["title"],
            unique=False,
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_conversations_title_trgm",
            table_name="conversations",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_documents_search_trgm",
            table_name="documents",
            postgresql_concurrently=True,
            if_exists=True,
        )
