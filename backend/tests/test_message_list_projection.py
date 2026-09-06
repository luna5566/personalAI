from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.request_limits import (
    CHAT_CITATION_LIMIT,
    CHAT_CITATION_TEXT_MAX_LENGTH,
    CHAT_HISTORY_CONTEXT_MESSAGE_MAX_LENGTH,
    DOCUMENT_TITLE_MAX_LENGTH,
    MESSAGE_LIST_CONTENT_PREVIEW_MAX_LENGTH,
)
from app.schemas.chat import Citation, MessageRead
from app.services import chat_service
from app.services.chat_service import _message_list_statement


def test_message_list_projection_bounds_content_and_excludes_private_columns() -> None:
    compiled = _message_list_statement().compile(dialect=postgresql.dialect())
    select_clause = str(compiled).split("FROM messages", maxsplit=1)[0]

    assert "left(messages.content" in select_clause
    assert "length(messages.content" in select_clause
    assert "jsonb_array_elements" in select_clause
    assert "jsonb_build_object" in select_clause
    assert "jsonb_agg" in select_clause
    assert "limited_citations" in select_clause
    values = list(compiled.params.values())
    assert values.count(MESSAGE_LIST_CONTENT_PREVIEW_MAX_LENGTH) == 2
    assert CHAT_CITATION_LIMIT in values
    assert CHAT_CITATION_TEXT_MAX_LENGTH in values
    assert values.count(DOCUMENT_TITLE_MAX_LENGTH) == 2
    for column in ("user_id", "metadata"):
        assert f"messages.{column}" not in select_clause
    for column in (
        "id",
        "conversation_id",
        "role",
        "created_at",
    ):
        assert f"messages.{column}" in select_clause
    assert "messages.citations AS citations" not in select_clause


def test_message_read_serializes_bounded_preview_and_truncation_marker() -> None:
    source = SimpleNamespace(
        id=uuid4(),
        conversation_id=uuid4(),
        role="assistant",
        content_preview="回答前缀",
        content_truncated=True,
        citations_preview=[],
        created_at=datetime.now(timezone.utc),
    )

    item = MessageRead.model_validate(source)
    payload = item.model_dump(mode="json")

    assert payload["content"] == "回答前缀"
    assert payload["content_truncated"] is True
    assert "content_preview" not in payload


def test_message_read_rejects_oversized_internal_preview() -> None:
    source = SimpleNamespace(
        id=uuid4(),
        conversation_id=uuid4(),
        role="assistant",
        content_preview="x" * (MESSAGE_LIST_CONTENT_PREVIEW_MAX_LENGTH + 1),
        content_truncated=True,
        citations_preview=[],
        created_at=datetime.now(timezone.utc),
    )

    with pytest.raises(ValidationError):
        MessageRead.model_validate(source)


def _citation_payload(**overrides):
    payload = {
        "document_id": str(uuid4()),
        "document_title": "资料",
        "source_type": "note",
        "chunk_id": str(uuid4()),
        "chunk_index": "2",
        "text": "引用内容",
        "score": "0.8123",
        "start_offset": "10",
        "end_offset": "14",
        "page_number": None,
        "section_title": None,
    }
    payload.update(overrides)
    return payload


def test_message_read_normalizes_projected_citations_and_discards_invalid_items() -> None:
    source = SimpleNamespace(
        id=uuid4(),
        conversation_id=uuid4(),
        role="assistant",
        content_preview="回答",
        content_truncated=False,
        citations_preview=[
            _citation_payload(),
            _citation_payload(document_id="not-a-uuid"),
        ],
        created_at=datetime.now(timezone.utc),
    )

    item = MessageRead.model_validate(source)

    assert len(item.citations) == 1
    assert item.citations[0].chunk_index == 2
    assert item.citations[0].score == 0.8123


def test_citation_schema_rejects_oversized_public_fields() -> None:
    with pytest.raises(ValidationError):
        Citation.model_validate(
            _citation_payload(
                text="x" * (CHAT_CITATION_TEXT_MAX_LENGTH + 1),
            )
        )

    with pytest.raises(ValidationError):
        Citation.model_validate(
            _citation_payload(
                document_title="x" * (DOCUMENT_TITLE_MAX_LENGTH + 1),
            )
        )


def test_conversation_history_projects_only_bounded_role_and_content() -> None:
    db = MagicMock()
    db.execute.return_value = []

    assert chat_service._conversation_history(db, uuid4()) == []

    statement = db.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    select_clause = str(compiled).split("FROM messages", maxsplit=1)[0]
    assert "messages.role" in select_clause
    assert "left(messages.content" in select_clause
    assert CHAT_HISTORY_CONTEXT_MESSAGE_MAX_LENGTH in compiled.params.values()
    for column in ("citations", "metadata", "user_id"):
        assert f"messages.{column}" not in select_clause
