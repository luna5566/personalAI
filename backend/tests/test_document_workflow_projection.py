from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.core.request_limits import (
    DOCUMENT_SUMMARY_MAX_LENGTH,
    RELATED_DOCUMENT_BODY_QUERY_MAX_LENGTH,
)
from app.services import document_service


def _compiled_select(statement):
    compiled = statement.compile(dialect=postgresql.dialect())
    select_clause = str(compiled).split("FROM documents", maxsplit=1)[0]
    return compiled, select_clause


def test_organization_reference_projection_excludes_document_payload() -> None:
    _, select_clause = _compiled_select(
        document_service._document_reference_statement()
    )

    assert "documents.id" in select_clause
    assert "documents.title" in select_clause
    assert "documents.status" in select_clause
    for column in (
        "raw_text",
        "cleaned_text",
        "summary",
        "metadata",
        "error_message",
        "file_path",
        "storage_scope",
    ):
        assert f"documents.{column}" not in select_clause


def test_collection_reference_query_has_hard_lookahead_limit() -> None:
    db = MagicMock()
    db.scalars.return_value = []

    document_service.list_document_references(
        db,
        uuid4(),
        [uuid4(), uuid4()],
        limit=21,
    )

    statement = db.scalars.call_args.args[0]
    _, select_clause = _compiled_select(statement)
    assert statement._limit_clause.value == 21
    assert "documents.raw_text" not in select_clause
    assert "documents.cleaned_text" not in select_clause


def test_related_source_projection_limits_summary_and_body_in_sql() -> None:
    compiled, select_clause = _compiled_select(
        document_service._related_document_source_statement()
    )
    sql = str(compiled)

    assert "left(documents.summary" in select_clause
    assert "left(coalesce(nullif(documents.cleaned_text" in select_clause
    assert DOCUMENT_SUMMARY_MAX_LENGTH in compiled.params.values()
    assert RELATED_DOCUMENT_BODY_QUERY_MAX_LENGTH in compiled.params.values()
    for column in (
        "metadata",
        "error_message",
        "file_path",
        "storage_scope",
        "created_at",
        "updated_at",
    ):
        assert f"documents.{column}" not in select_clause
    assert "FROM documents" in sql


def test_deletion_reference_projection_is_narrow_and_locks_target() -> None:
    db = MagicMock()
    db.execute.return_value.one_or_none.return_value = None

    result = document_service._get_document_storage_reference(
        db,
        uuid4(),
        uuid4(),
    )

    assert result is None
    statement = db.execute.call_args.args[0]
    _, select_clause = _compiled_select(statement)
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
    for column in (
        "raw_text",
        "cleaned_text",
        "summary",
        "metadata",
        "error_message",
        "original_filename",
        "mime_type",
    ):
        assert f"documents.{column}" not in select_clause
