"""add chunk embedding vector index

Revision ID: 0009_vector_index
Revises: 0008_users
Create Date: 2026-05-17
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009_vector_index"
down_revision: Union[str, None] = "0008_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_embedding_hnsw
        ON chunk_embeddings
        USING hnsw (embedding vector_l2_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunk_embeddings_embedding_hnsw")
