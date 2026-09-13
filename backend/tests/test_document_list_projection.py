from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.request_limits import (
    DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH,
    DOCUMENT_LIST_SUMMARY_PREVIEW_MAX_LENGTH,
)
from app.schemas.document import DocumentListItem
from app.services.document_service import _document_list_statement


def test_document_list_projection_excludes_large_and_detail_only_columns() -> None:
    compiled = _document_list_statement().compile(
        dialect=postgresql.dialect()
    )
    sql = str(compiled)
    select_clause = sql.split("FROM documents", maxsplit=1)[0]

    assert "left(documents.summary" in select_clause
    assert "left(documents.error_message" in select_clause
    assert sorted(compiled.params.values()) == [500, 500]
    for column in (
        "user_id",
        "original_filename",
        "file_path",
        "storage_backend",
        "storage_scope",
        "file_size",
        "mime_type",
        "raw_text",
        "cleaned_text",
        "metadata",
    ):
        assert f"documents.{column}" not in select_clause
    for column in (
        "id",
        "title",
        "source_type",
        "status",
        "created_at",
        "updated_at",
    ):
        assert f"documents.{column}" in select_clause


def test_document_list_item_serializes_preview_attributes_under_api_names() -> None:
    now = datetime.now(UTC)
    source = SimpleNamespace(
        id=uuid4(),
        title="资料标题",
        source_type="note",
        summary_preview="摘要预览",
        status="indexed",
        error_message_preview="错误预览",
        tags=["学习"],
        created_at=now,
        updated_at=now,
    )

    item = DocumentListItem.model_validate(source)
    payload = item.model_dump(mode="json")

    assert payload["summary"] == "摘要预览"
    assert payload["error_message"] == "错误预览"
    assert "summary_preview" not in payload
    assert "error_message_preview" not in payload


@pytest.mark.parametrize(
    ("attribute", "length"),
    [
        (
            "summary_preview",
            DOCUMENT_LIST_SUMMARY_PREVIEW_MAX_LENGTH + 1,
        ),
        (
            "error_message_preview",
            DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH + 1,
        ),
    ],
)
def test_document_list_item_rejects_oversized_internal_previews(
    attribute: str,
    length: int,
) -> None:
    now = datetime.now(UTC)
    source = SimpleNamespace(
        id=uuid4(),
        title="资料标题",
        source_type="note",
        summary_preview=None,
        status="indexed",
        error_message_preview=None,
        tags=[],
        created_at=now,
        updated_at=now,
    )
    setattr(source, attribute, "x" * length)

    with pytest.raises(ValidationError):
        DocumentListItem.model_validate(source)
