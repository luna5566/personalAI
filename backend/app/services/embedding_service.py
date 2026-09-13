import sys
import tempfile
from array import array
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.embedding_provider import EmbeddingProvider, get_embedding_provider
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.models.embedding import ChunkEmbedding

EMBEDDING_SPOOL_MEMORY_BYTES = 8 * 1024 * 1024
_FLOAT_ARRAY_ITEM_BYTES = array("f").itemsize
_CHUNK_ID_BYTES = 16


@dataclass(frozen=True)
class _StoredChunkInput:
    id: UUID
    content: str


def embed_document_chunks(
    db: Session,
    document: Document,
    chunks: list[DocumentChunk] | None = None,
    provider: EmbeddingProvider | None = None,
    batch_size: int = 64,
) -> int:
    _validate_batch_size(batch_size)
    provider = provider or get_embedding_provider()
    document_id = document.id
    user_id = getattr(document, "user_id", None)
    if user_id is None and chunks:
        user_id = chunks[0].user_id
    if user_id is None:
        raise ValueError("Document owner is required for embedding persistence")

    with tempfile.SpooledTemporaryFile(
        max_size=EMBEDDING_SPOOL_MEMORY_BYTES,
        mode="w+b",
    ) as spool:
        chunk_count = _spool_chunk_vectors(
            spool,
            _iter_chunk_batches(
                db,
                document_id,
                chunks=chunks,
                batch_size=batch_size,
            ),
            provider=provider,
        )
        if chunk_count == 0:
            raise ValueError("Document has no chunks to embed")
        db.execute(
            delete(ChunkEmbedding).where(
                ChunkEmbedding.document_id == document_id
            )
        )
        document.status = DocumentStatus.EMBEDDING.value
        persisted = _persist_spooled_embeddings(
            db,
            spool,
            chunk_count=chunk_count,
            user_id=user_id,
            document_id=document_id,
            provider=provider,
            batch_size=batch_size,
        )

    document.status = DocumentStatus.INDEXED.value
    return persisted


def generate_chunk_embeddings(
    chunks: list[DocumentChunk],
    *,
    provider: EmbeddingProvider | None = None,
    batch_size: int = 64,
) -> list[ChunkEmbedding]:
    _validate_batch_size(batch_size)
    provider = provider or get_embedding_provider()
    embeddings: list[ChunkEmbedding] = []
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors = provider.embed_texts([chunk.content for chunk in batch])
        embeddings.extend(_build_embeddings(batch, vectors, provider))
    return embeddings


def _build_embeddings(
    chunks: list[DocumentChunk],
    vectors: list[list[float]],
    provider: EmbeddingProvider,
) -> list[ChunkEmbedding]:
    _validate_embedding_vectors(
        vectors,
        expected_count=len(chunks),
        dimensions=provider.dimensions,
    )

    return [
        ChunkEmbedding(
            chunk_id=chunk.id,
            user_id=chunk.user_id,
            document_id=chunk.document_id,
            embedding=vector,
            embedding_model=provider.index_id,
            embedding_dimensions=provider.dimensions,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]


def _spool_chunk_vectors(
    spool,
    chunk_batches,
    *,
    provider: EmbeddingProvider,
) -> int:
    if _FLOAT_ARRAY_ITEM_BYTES != 4:
        raise RuntimeError("Embedding spooling requires 32-bit C floats")
    spooled = 0
    for batch in chunk_batches:
        vectors = provider.embed_texts([chunk.content for chunk in batch])
        _validate_embedding_vectors(
            vectors,
            expected_count=len(batch),
            dimensions=provider.dimensions,
        )
        for chunk, vector in zip(batch, vectors, strict=True):
            try:
                chunk_id = (
                    chunk.id
                    if isinstance(chunk.id, UUID)
                    else UUID(str(chunk.id))
                )
                values = array("f", vector)
            except (OverflowError, TypeError, ValueError) as exc:
                raise ValueError(
                    "Embedding provider returned invalid vector values"
                ) from exc
            if sys.byteorder != "little":
                values.byteswap()
            spool.write(chunk_id.bytes)
            spool.write(values.tobytes())
            spooled += 1
    return spooled


def _iter_chunk_batches(
    db: Session,
    document_id: UUID,
    *,
    chunks: list[DocumentChunk] | None,
    batch_size: int,
):
    if chunks is not None:
        for start in range(0, len(chunks), batch_size):
            yield chunks[start : start + batch_size]
        return

    cursor: int | None = None
    while True:
        statement = select(
            DocumentChunk.id,
            DocumentChunk.chunk_index,
            DocumentChunk.content,
        ).where(DocumentChunk.document_id == document_id)
        if cursor is not None:
            statement = statement.where(DocumentChunk.chunk_index > cursor)
        rows = list(
            db.execute(
                statement.order_by(DocumentChunk.chunk_index).limit(batch_size)
            )
        )
        db.rollback()
        if not rows:
            return
        yield [
            _StoredChunkInput(id=row.id, content=row.content)
            for row in rows
        ]
        cursor = rows[-1].chunk_index


def _persist_spooled_embeddings(
    db: Session,
    spool,
    *,
    chunk_count: int,
    user_id: UUID,
    document_id: UUID,
    provider: EmbeddingProvider,
    batch_size: int,
) -> int:
    spool.seek(0)
    persisted = 0
    vector_bytes = provider.dimensions * _FLOAT_ARRAY_ITEM_BYTES
    for start in range(0, chunk_count, batch_size):
        current_batch_size = min(batch_size, chunk_count - start)
        embeddings: list[ChunkEmbedding] = []
        for _ in range(current_batch_size):
            raw_chunk_id = spool.read(_CHUNK_ID_BYTES)
            if len(raw_chunk_id) != _CHUNK_ID_BYTES:
                raise RuntimeError(
                    "Embedding spool ended before all chunk IDs were read"
                )
            payload = spool.read(vector_bytes)
            if len(payload) != vector_bytes:
                raise RuntimeError(
                    "Embedding spool ended before all vectors were read"
                )
            values = array("f")
            values.frombytes(payload)
            if sys.byteorder != "little":
                values.byteswap()
            embeddings.append(
                ChunkEmbedding(
                    chunk_id=UUID(bytes=raw_chunk_id),
                    user_id=user_id,
                    document_id=document_id,
                    embedding=values.tolist(),
                    embedding_model=provider.index_id,
                    embedding_dimensions=provider.dimensions,
                )
            )
        db.add_all(embeddings)
        db.flush()
        for embedding in embeddings:
            db.expunge(embedding)
        persisted += len(embeddings)
    if spool.read(1):
        raise RuntimeError("Embedding spool contained unexpected trailing data")
    return persisted


def _validate_batch_size(batch_size: int) -> None:
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("Embedding batch size must be a positive integer")


def _validate_embedding_vectors(
    vectors: list[list[float]],
    *,
    expected_count: int,
    dimensions: int,
) -> None:
    if len(vectors) != expected_count:
        raise ValueError("Embedding provider returned a different number of vectors")
    if any(len(vector) != dimensions for vector in vectors):
        raise ValueError("Embedding provider returned vectors with unexpected dimensions")
