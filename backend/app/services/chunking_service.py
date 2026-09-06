from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.rag.chunker import ChunkData, iter_text_chunks, split_text_into_chunks
from app.utils.hash import sha256_text
from app.utils.text_cleaner import clean_text


CHUNK_PERSIST_BATCH_SIZE = 256


def recreate_document_chunks(
    db: Session,
    document: Document,
    *,
    batch_size: int = CHUNK_PERSIST_BATCH_SIZE,
) -> int:
    _validate_batch_size(batch_size)
    cleaned = _cleaned_document_text(document)
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    persisted = 0
    batch: list[DocumentChunk] = []
    for item in iter_text_chunks(cleaned):
        batch.append(_document_chunk(document, item))
        if len(batch) == batch_size:
            _persist_chunk_batch(db, batch)
            persisted += len(batch)
            batch = []
    if batch:
        _persist_chunk_batch(db, batch)
        persisted += len(batch)
    return persisted


def build_document_chunks(document: Document) -> list[DocumentChunk]:
    cleaned = _cleaned_document_text(document)

    return [
        _document_chunk(document, item)
        for item in split_text_into_chunks(cleaned)
    ]


def _document_chunk(document: Document, item: ChunkData) -> DocumentChunk:
    return DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        user_id=document.user_id,
        chunk_index=item.chunk_index,
        content=item.content,
        content_hash=sha256_text(item.content),
        char_count=item.char_count,
        start_offset=item.start_offset,
        end_offset=item.end_offset,
        page_number=item.page_number,
        section_title=item.section_title,
        metadata_={},
    )


def _cleaned_document_text(document: Document) -> str:
    if document.cleaned_text:
        return document.cleaned_text
    cleaned = clean_text(document.raw_text or "")
    document.cleaned_text = cleaned
    return cleaned


def _persist_chunk_batch(
    db: Session,
    chunks: list[DocumentChunk],
) -> None:
    db.add_all(chunks)
    db.flush()
    for chunk in chunks:
        db.expunge(chunk)


def _validate_batch_size(batch_size: int) -> None:
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("Chunk batch size must be a positive integer")
