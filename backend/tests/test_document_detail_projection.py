from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.request_limits import (
    DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH,
    DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH,
    DOCUMENT_SUMMARY_MAX_LENGTH,
)
from app.schemas.document import DocumentRead, DocumentUpdate
from app.services import document_service


def test_document_detail_selects_one_canonical_content_and_no_internal_payload() -> None:
    compiled = document_service._document_detail_statement().compile(
        dialect=postgresql.dialect()
    )
    select_clause = str(compiled).split("FROM documents", maxsplit=1)[0]

    assert "substr(coalesce(nullif(documents.cleaned_text" in select_clause
    assert "char_length(coalesce(nullif(documents.cleaned_text" in select_clause
    assert "coalesce(nullif(documents.cleaned_text" in select_clause
    assert "nullif(documents.raw_text" in select_clause
    assert "left(documents.summary" in select_clause
    assert "left(documents.error_message" in select_clause
    assert DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH in compiled.params.values()
    assert DOCUMENT_SUMMARY_MAX_LENGTH in compiled.params.values()
    assert DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH in compiled.params.values()
    for column in (
        "documents.file_path",
        "documents.storage_backend",
        "documents.storage_scope",
        "documents.metadata",
    ):
        assert column not in select_clause


def test_document_detail_view_serializes_only_canonical_content() -> None:
    now = datetime.now(timezone.utc)
    view = document_service.DocumentDetailView(
        id=uuid4(),
        user_id=uuid4(),
        title="资料",
        source_type="note",
        original_filename=None,
        file_size=None,
        mime_type=None,
        content="清洗正文",
        content_source="cleaned_text",
        content_offset=0,
        content_length=4,
        content_truncated=False,
        summary="摘要",
        status="indexed",
        error_message=None,
        created_at=now,
        updated_at=now,
        tags=["学习"],
    )

    payload = DocumentRead.model_validate(view).model_dump(mode="json")

    assert payload["content"] == "清洗正文"
    assert payload["content_source"] == "cleaned_text"
    assert payload["content_offset"] == 0
    assert payload["content_length"] == 4
    assert payload["content_truncated"] is False
    for field in (
        "raw_text",
        "cleaned_text",
        "file_path",
        "metadata",
    ):
        assert field not in payload


def test_document_detail_schema_rejects_content_larger_than_one_window() -> None:
    now = datetime.now(timezone.utc)

    with pytest.raises(ValidationError):
        DocumentRead.model_validate(
            document_service.DocumentDetailView(
                id=uuid4(),
                user_id=uuid4(),
                title="资料",
                source_type="note",
                original_filename=None,
                file_size=None,
                mime_type=None,
                content="x" * (DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH + 1),
                content_source="cleaned_text",
                content_offset=0,
                content_length=DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH + 1,
                content_truncated=False,
                summary=None,
                status="indexed",
                error_message=None,
                created_at=now,
                updated_at=now,
            )
        )


def test_in_memory_detail_prefers_cleaned_content_and_bounds_diagnostics() -> None:
    now = datetime.now(timezone.utc)
    document = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        title="资料",
        source_type="note",
        original_filename=None,
        file_size=None,
        mime_type=None,
        cleaned_text="清洗正文",
        raw_text="原始正文",
        summary="s" * (DOCUMENT_SUMMARY_MAX_LENGTH + 1),
        status="indexed",
        error_message="e" * (DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH + 1),
        created_at=now,
        updated_at=now,
        tags=["学习"],
    )

    view = document_service.to_document_detail_view(document)

    assert view.content == "清洗正文"
    assert view.content_source == "cleaned_text"
    assert view.content_offset == 0
    assert view.content_length == 4
    assert view.content_truncated is False
    assert len(view.summary or "") == DOCUMENT_SUMMARY_MAX_LENGTH
    assert len(view.error_message or "") == DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH


def test_in_memory_detail_returns_bounded_content_windows() -> None:
    now = datetime.now(timezone.utc)
    body = "a" * DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH + "结尾内容"
    document = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        title="大资料",
        source_type="note",
        original_filename=None,
        file_size=None,
        mime_type=None,
        cleaned_text=body,
        raw_text="",
        summary=None,
        status="indexed",
        error_message=None,
        created_at=now,
        updated_at=now,
        tags=[],
    )

    first = document_service.to_document_detail_view(document)
    last = document_service.to_document_detail_view(
        document,
        content_offset=DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH,
    )
    beyond = document_service.to_document_detail_view(
        document,
        content_offset=len(body) + 1,
    )

    assert len(first.content or "") == DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH
    assert first.content_offset == 0
    assert first.content_length == len(body)
    assert first.content_truncated is True
    assert last.content == "结尾内容"
    assert last.content_offset == DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH
    assert last.content_length == len(body)
    assert last.content_truncated is False
    assert beyond.content is None
    assert beyond.content_offset == len(body) + 1
    assert beyond.content_length == len(body)
    assert beyond.content_truncated is False


def test_document_update_uses_jsonb_sql_without_loading_document(
    monkeypatch,
) -> None:
    document_id = uuid4()
    user_id = uuid4()
    db = MagicMock()
    db.scalar.return_value = document_id
    applied_tags = []
    monkeypatch.setattr(
        document_service.tag_service,
        "set_document_tags",
        lambda db, owner, target, tags: applied_tags.extend(tags),
    )

    updated_id = document_service.update_document(
        db,
        user_id,
        document_id,
        DocumentUpdate(title="新标题", tags=["学习"]),
    )

    assert updated_id == document_id
    statement = db.scalar.call_args_list[0].args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert sql.startswith("UPDATE documents SET")
    assert "jsonb_set(documents.metadata" in sql
    assert "RETURNING documents.id" in sql
    assert "documents.raw_text" not in sql
    assert "documents.cleaned_text" not in sql
    assert applied_tags == ["学习"]
    db.commit.assert_called_once_with()
