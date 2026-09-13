from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.request_limits import (
    CHAT_SCOPE_DOCUMENT_LIMIT,
    CHAT_SCOPE_SOURCE_TYPE_LIMIT,
    CHAT_SCOPE_TAG_LIMIT,
    DOCUMENT_TAG_LIMIT,
    NOTE_CONTENT_MAX_LENGTH,
    TAG_NAME_MAX_LENGTH,
)
from app.models.document import DocumentSourceType
from app.schemas.chat import ChatQueryRequest, ChatScope, ConversationUpdate
from app.schemas.document import DocumentUpdate, NoteCreate
from app.schemas.organize import OrganizeCollectionRequest, OrganizeResultSaveRequest
from app.schemas.tag import TagUpdate


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (NoteCreate, {"content": "   "}),
        (ChatQueryRequest, {"question": "\n\t"}),
        (ConversationUpdate, {"title": "   "}),
        (DocumentUpdate, {"title": "   "}),
        (TagUpdate, {"name": "   "}),
        (
            OrganizeResultSaveRequest,
            {
                "title": "整理结果",
                "result": "   ",
                "source_document_ids": ["00000000-0000-0000-0000-000000000001"],
            },
        ),
    ],
)
def test_rejects_blank_user_input(schema, payload) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_scope_and_question_values_are_trimmed() -> None:
    request = ChatQueryRequest(
        question="  如何整理？  ",
        scope=ChatScope(tags=["  学习  "]),
    )

    assert request.question == "如何整理？"
    assert request.scope is not None
    assert request.scope.tags == ["学习"]


def test_collection_organize_limits_manual_scope_size() -> None:
    with pytest.raises(ValidationError):
        OrganizeCollectionRequest(document_ids=[uuid4() for _ in range(21)])


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (
            NoteCreate,
            {
                "content": "content",
                "tags": [f"tag-{index}" for index in range(DOCUMENT_TAG_LIMIT + 1)],
            },
        ),
        (
            DocumentUpdate,
            {"tags": ["x" * (TAG_NAME_MAX_LENGTH + 1)]},
        ),
        (
            ChatScope,
            {
                "document_ids": [
                    uuid4() for _ in range(CHAT_SCOPE_DOCUMENT_LIMIT + 1)
                ]
            },
        ),
        (
            ChatScope,
            {
                "tags": [
                    f"tag-{index}" for index in range(CHAT_SCOPE_TAG_LIMIT + 1)
                ]
            },
        ),
        (
            ChatScope,
            {
                "source_types": [
                    "note" for _ in range(CHAT_SCOPE_SOURCE_TYPE_LIMIT + 1)
                ]
            },
        ),
        (ChatScope, {"tags": ["   "]}),
    ],
)
def test_rejects_oversized_request_collections(schema, payload) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_accepts_request_collections_at_their_limits() -> None:
    assert len(DocumentSourceType) == CHAT_SCOPE_SOURCE_TYPE_LIMIT

    note = NoteCreate(
        content="content",
        tags=[f"tag-{index}" for index in range(DOCUMENT_TAG_LIMIT)],
    )
    scope = ChatScope(
        document_ids=[uuid4() for _ in range(CHAT_SCOPE_DOCUMENT_LIMIT)],
        tags=[f"tag-{index}" for index in range(CHAT_SCOPE_TAG_LIMIT)],
        source_types=[
            "note" for _ in range(CHAT_SCOPE_SOURCE_TYPE_LIMIT)
        ],
    )

    assert len(note.tags) == DOCUMENT_TAG_LIMIT
    assert len(scope.document_ids) == CHAT_SCOPE_DOCUMENT_LIMIT
    assert len(scope.tags) == CHAT_SCOPE_TAG_LIMIT
    assert len(scope.source_types) == CHAT_SCOPE_SOURCE_TYPE_LIMIT


def test_note_content_length_is_bounded() -> None:
    note = NoteCreate(content="x" * NOTE_CONTENT_MAX_LENGTH)

    assert len(note.content) == NOTE_CONTENT_MAX_LENGTH
    with pytest.raises(ValidationError):
        NoteCreate(content="x" * (NOTE_CONTENT_MAX_LENGTH + 1))
