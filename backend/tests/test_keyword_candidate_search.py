from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.models.chunk import DocumentChunk
from app.services import retrieval_service


def test_keyword_candidates_are_indexed_and_ranked_before_limit() -> None:
    db = MagicMock()
    db.execute.return_value = []

    assert retrieval_service.keyword_search(
        db,
        uuid4(),
        "alpha beta",
        top_k=8,
    ) == []

    statement = db.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "WITH keyword_candidate_chunks AS" in sql
    assert "UNION" in sql
    assert "coalesce(document_chunks.content" in sql.lower()
    assert "ORDER BY" in sql
    assert "least(" in sql.lower()
    assert "document_chunks.id" in sql
    assert statement._limit_clause.value == 48


def test_chunk_search_index_uses_trigram_gin() -> None:
    index = next(
        index
        for index in DocumentChunk.__table__.indexes
        if index.name == "ix_document_chunks_search_trgm"
    )
    sql = str(CreateIndex(index).compile(dialect=postgresql.dialect())).lower()
    assert "using gin" in sql
    assert "gin_trgm_ops" in sql
    assert "coalesce(content, ''::text)" in sql
    assert "coalesce(section_title, ''::character varying)" in sql
