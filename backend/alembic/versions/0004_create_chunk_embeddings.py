"""create chunk embeddings table

Revision ID: 0004_create_chunk_embeddings
Revises: 0003_create_document_chunks
Create Date: 2026-05-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0004_create_chunk_embeddings"
down_revision: Union[str, None] = "0003_create_document_chunks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_chunk_embeddings_chunk_id", "chunk_embeddings", ["chunk_id"], unique=True)
    op.create_index("ix_chunk_embeddings_user_id", "chunk_embeddings", ["user_id"])
    op.create_index("ix_chunk_embeddings_document_id", "chunk_embeddings", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_chunk_embeddings_document_id", table_name="chunk_embeddings")
    op.drop_index("ix_chunk_embeddings_user_id", table_name="chunk_embeddings")
    op.drop_index("ix_chunk_embeddings_chunk_id", table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")
