from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.request_limits import RETRIEVAL_CHUNK_CONTENT_MAX_LENGTH
from app.models.chunk import DocumentChunk


@dataclass(frozen=True)
class ContextChunk:
    document_id: UUID
    chunk_index: int
    content: str


def _context_chunk_columns() -> tuple:
    return (
        DocumentChunk.document_id.label("document_id"),
        DocumentChunk.chunk_index.label("chunk_index"),
        func.left(
            DocumentChunk.content,
            RETRIEVAL_CHUNK_CONTENT_MAX_LENGTH,
        ).label("content"),
    )


def load_context_chunks(
    db: Session,
    document_ids: list[UUID],
    *,
    limit: int,
    user_id: UUID | None = None,
) -> list[ContextChunk]:
    if not document_ids or limit <= 0:
        return []
    statement = select(*_context_chunk_columns()).where(
        DocumentChunk.document_id.in_(document_ids)
    )
    if user_id is not None:
        statement = statement.where(DocumentChunk.user_id == user_id)
    rows = db.execute(
        statement.order_by(
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
        ).limit(limit)
    )
    return [ContextChunk(*row) for row in rows]


def load_partitioned_context_chunks(
    db: Session,
    user_id: UUID,
    document_ids: list[UUID],
    *,
    per_document_limit: int,
) -> list[ContextChunk]:
    if not document_ids or per_document_limit <= 0:
        return []
    row_number = func.row_number().over(
        partition_by=DocumentChunk.document_id,
        order_by=DocumentChunk.chunk_index,
    ).label("document_row_number")
    ranked = (
        select(*_context_chunk_columns(), row_number)
        .where(
            DocumentChunk.user_id == user_id,
            DocumentChunk.document_id.in_(document_ids),
        )
        .subquery("ranked_context_chunks")
    )
    rows = db.execute(
        select(
            ranked.c.document_id,
            ranked.c.chunk_index,
            ranked.c.content,
        )
        .where(ranked.c.document_row_number <= per_document_limit)
        .order_by(ranked.c.document_id, ranked.c.chunk_index)
    )
    return [ContextChunk(*row) for row in rows]
