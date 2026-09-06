from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.core.request_limits import RETRIEVAL_CHUNK_CONTENT_MAX_LENGTH
from app.services import context_chunk_service
from app.services.context_chunk_service import ContextChunk


def test_context_chunk_query_returns_bounded_scalar_rows() -> None:
    document_id = uuid4()
    db = MagicMock()
    db.execute.return_value = [(document_id, 0, "内容")]

    chunks = context_chunk_service.load_context_chunks(
        db,
        [document_id],
        user_id=uuid4(),
        limit=8,
    )

    assert chunks == [
        ContextChunk(
            document_id=document_id,
            chunk_index=0,
            content="内容",
        )
    ]
    statement = db.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    select_clause = str(compiled).split(
        "FROM document_chunks",
        maxsplit=1,
    )[0]
    assert statement._limit_clause.value == 8
    assert "left(document_chunks.content" in select_clause
    assert RETRIEVAL_CHUNK_CONTENT_MAX_LENGTH in compiled.params.values()
    for column in (
        "document_chunks.id",
        "document_chunks.user_id",
        "document_chunks.content_hash",
        "document_chunks.summary",
        "document_chunks.token_count",
        "document_chunks.metadata",
        "document_chunks.created_at",
    ):
        assert column not in select_clause


def test_partitioned_context_query_ranks_only_bounded_scalar_rows() -> None:
    db = MagicMock()
    db.execute.return_value = []

    chunks = context_chunk_service.load_partitioned_context_chunks(
        db,
        uuid4(),
        [uuid4(), uuid4()],
        per_document_limit=4,
    )

    assert chunks == []
    statement = db.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "row_number() OVER" in sql
    assert "ranked_context_chunks.document_row_number" in sql
    assert "left(document_chunks.content" in sql
    assert "document_chunks.metadata" not in sql
    assert "document_chunks.content_hash" not in sql
    assert 4 in compiled.params.values()


def test_context_chunk_queries_skip_invalid_empty_work() -> None:
    db = MagicMock()

    assert context_chunk_service.load_context_chunks(db, [], limit=8) == []
    assert context_chunk_service.load_partitioned_context_chunks(
        db,
        uuid4(),
        [uuid4()],
        per_document_limit=0,
    ) == []
    db.execute.assert_not_called()
