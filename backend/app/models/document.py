from datetime import datetime
from enum import Enum
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    literal,
    literal_column,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, query_expression, relationship

from app.core.database import Base


class DocumentSourceType(str, Enum):
    NOTE = "note"
    PDF = "pdf"
    TXT = "txt"
    MARKDOWN = "markdown"
    IMAGE = "image"
    AUDIO = "audio"
    DOCX = "docx"
    HTML = "html"
    EXCEL = "excel"
    EPUB = "epub"
    AI_GENERATED = "ai_generated"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    SUMMARIZING = "summarizing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "(file_path IS NULL AND storage_backend IS NULL AND storage_scope IS NULL) "
            "OR (file_path IS NOT NULL AND storage_backend IS NOT NULL "
            "AND storage_scope IS NOT NULL)",
            name="ck_documents_file_storage_provenance",
        ),
        Index("ix_documents_user_status", "user_id", "status"),
        Index("ix_documents_user_source_type", "user_id", "source_type"),
        Index(
            "ix_documents_user_created_id",
            "user_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)

    original_filename: Mapped[str | None] = mapped_column(String(255))
    file_path: Mapped[str | None] = mapped_column(Text)
    storage_backend: Mapped[str | None] = mapped_column(String(32))
    storage_scope: Mapped[str | None] = mapped_column(Text)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    mime_type: Mapped[str | None] = mapped_column(String(128))

    raw_text: Mapped[str | None] = mapped_column(Text)
    cleaned_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    summary_preview: Mapped[str | None] = query_expression()

    status: Mapped[str] = mapped_column(String(32), nullable=False, default=DocumentStatus.UPLOADED.value)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_message_preview: Mapped[str | None] = query_expression()
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    tag_links = relationship("DocumentTag", back_populates="document", cascade="all, delete-orphan")


def document_search_text_expression():
    return (
        func.coalesce(Document.title, "")
        + literal(" ")
        + func.coalesce(Document.raw_text, "")
        + literal(" ")
        + func.coalesce(Document.cleaned_text, "")
        + literal(" ")
        + func.coalesce(Document.summary, "")
    )


DOCUMENT_SEARCH_INDEX_EXPRESSION = (
    "((((((COALESCE(title, ''::character varying)::text || ' '::text) || "
    "COALESCE(raw_text, ''::text)) || ' '::text) || "
    "COALESCE(cleaned_text, ''::text)) || ' '::text) || "
    "COALESCE(summary, ''::text))"
)


document_search_index = Index(
    "ix_documents_search_trgm",
    literal_column(DOCUMENT_SEARCH_INDEX_EXPRESSION).label(
        "document_search_text"
    ),
    postgresql_using="gin",
    postgresql_ops={"document_search_text": "gin_trgm_ops"},
)
document_search_index._set_parent(Document.__table__)


DOCUMENT_FILE_PATH_HASH_INDEX_EXPRESSION = "md5(file_path)"


document_file_path_hash_index = Index(
    "ix_documents_file_path_md5",
    literal_column(DOCUMENT_FILE_PATH_HASH_INDEX_EXPRESSION).label(
        "file_path_md5"
    ),
    postgresql_where=literal_column("file_path IS NOT NULL"),
)
document_file_path_hash_index._set_parent(Document.__table__)
