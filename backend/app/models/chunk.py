from datetime import datetime
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    literal,
    literal_column,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_document_index"),
        Index("ix_document_chunks_user_document", "user_id", "document_id"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    summary: Mapped[str | None] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(String(255))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document = relationship("Document", back_populates="chunks")
    embedding = relationship("ChunkEmbedding", back_populates="chunk", cascade="all, delete-orphan", uselist=False)


def chunk_search_text_expression():
    return (
        func.coalesce(DocumentChunk.content, "")
        + literal(" ")
        + func.coalesce(DocumentChunk.section_title, "")
    )


CHUNK_SEARCH_INDEX_EXPRESSION = (
    "((COALESCE(content, ''::text) || ' '::text) || "
    "COALESCE(section_title, ''::character varying)::text)"
)


chunk_search_index = Index(
    "ix_document_chunks_search_trgm",
    literal_column(CHUNK_SEARCH_INDEX_EXPRESSION).label(
        "chunk_search_text"
    ),
    postgresql_using="gin",
    postgresql_ops={"chunk_search_text": "gin_trgm_ops"},
)
chunk_search_index._set_parent(DocumentChunk.__table__)
