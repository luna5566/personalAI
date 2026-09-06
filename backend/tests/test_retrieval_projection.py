from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.core.request_limits import RETRIEVAL_CHUNK_CONTENT_MAX_LENGTH
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.rag.context_builder import build_context
from app.services import retrieval_service
from app.services.retrieval_service import RetrievedChunk


def test_retrieval_projection_selects_only_public_chunk_fields() -> None:
    statement = (
        select(*retrieval_service._retrieval_result_columns())
        .select_from(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    select_clause = str(compiled).split(
        "FROM document_chunks",
        maxsplit=1,
    )[0]

    assert "left(document_chunks.content" in select_clause
    assert "least(document_chunks.end_offset" in select_clause
    assert RETRIEVAL_CHUNK_CONTENT_MAX_LENGTH in compiled.params.values()
    for column in (
        "documents.raw_text",
        "documents.cleaned_text",
        "documents.summary",
        "documents.metadata",
        "documents.error_message",
        "document_chunks.summary",
        "document_chunks.metadata",
        "document_chunks.content_hash",
        "document_chunks.token_count",
    ):
        assert column not in select_clause


def test_retrieved_chunk_is_built_without_orm_entities() -> None:
    row = SimpleNamespace(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title="窄行资料",
        source_type="note",
        chunk_index=3,
        content="检索内容",
        start_offset=12,
        end_offset=16,
        page_number=None,
        section_title="章节",
    )

    result = retrieval_service._retrieved_chunk_from_row(row, score=0.8)

    assert result == RetrievedChunk(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        document_title="窄行资料",
        source_type="note",
        chunk_index=3,
        content="检索内容",
        start_offset=12,
        end_offset=16,
        score=0.8,
        page_number=None,
        section_title="章节",
    )


def test_context_hard_limit_applies_to_the_first_legacy_wide_chunk() -> None:
    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title="历史资料",
        source_type="note",
        chunk_index=0,
        content="宽" * 20_000,
        start_offset=0,
        end_offset=20_000,
        score=0.9,
    )

    context = build_context([chunk], max_chars=1_000)

    assert len(context) == 1_000
    assert context.startswith("[资料 1]\n标题：历史资料")


def test_context_returns_empty_for_non_positive_limit() -> None:
    assert build_context([], max_chars=0) == ""


def test_context_limit_includes_separators_between_chunks() -> None:
    chunks = [
        RetrievedChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            document_title=f"资料 {index}",
            source_type="note",
            chunk_index=0,
            content="内容" * 20,
            start_offset=0,
            end_offset=40,
            score=0.9,
        )
        for index in range(3)
    ]

    context = build_context(chunks, max_chars=140)

    assert len(context) <= 140
    assert context.count("\n\n") == 1
