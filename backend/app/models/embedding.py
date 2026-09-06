from datetime import datetime
from uuid import UUID as PyUUID
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import (
    DATABASE_HNSW_EF_CONSTRUCTION,
    DATABASE_HNSW_M,
    DATABASE_VECTOR_DIMENSIONS,
)
from app.core.database import Base


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        Index(
            "ix_chunk_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_l2_ops"},
            postgresql_with={
                "m": DATABASE_HNSW_M,
                "ef_construction": DATABASE_HNSW_EF_CONSTRUCTION,
            },
        ),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    chunk_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    document_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(DATABASE_VECTOR_DIMENSIONS), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    chunk = relationship("DocumentChunk", back_populates="embedding")
