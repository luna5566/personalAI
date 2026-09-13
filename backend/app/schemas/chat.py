from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from app.core.request_limits import (
    CHAT_ANSWER_MAX_LENGTH,
    CHAT_CITATION_LIMIT,
    CHAT_CITATION_TEXT_MAX_LENGTH,
    CHAT_SCOPE_DOCUMENT_LIMIT,
    CHAT_SCOPE_SOURCE_TYPE_LIMIT,
    CHAT_SCOPE_TAG_LIMIT,
    DOCUMENT_TITLE_MAX_LENGTH,
    MESSAGE_LIST_CONTENT_PREVIEW_MAX_LENGTH,
    TAG_NAME_MAX_LENGTH,
)
from app.models.document import DocumentSourceType

ChatScopeTagName = Annotated[
    str,
    Field(min_length=1, max_length=TAG_NAME_MAX_LENGTH),
]


class ChatScope(BaseModel):
    document_ids: list[UUID] = Field(
        default_factory=list,
        max_length=CHAT_SCOPE_DOCUMENT_LIMIT,
    )
    tags: list[ChatScopeTagName] = Field(
        default_factory=list,
        max_length=CHAT_SCOPE_TAG_LIMIT,
    )
    source_types: list[DocumentSourceType] = Field(
        default_factory=list,
        max_length=CHAT_SCOPE_SOURCE_TYPE_LIMIT,
    )
    # Limit retrieval to documents created within the last N days (1–365).
    recent_days: int | None = Field(default=None, ge=1, le=365)

    model_config = ConfigDict(str_strip_whitespace=True)


class ChatQueryRequest(BaseModel):
    conversation_id: UUID | None = None
    question: str = Field(min_length=1, max_length=4000)
    scope: ChatScope | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class Citation(BaseModel):
    document_id: UUID
    document_title: str = Field(max_length=DOCUMENT_TITLE_MAX_LENGTH)
    source_type: DocumentSourceType
    chunk_id: UUID
    chunk_index: int = Field(ge=0)
    text: str = Field(max_length=CHAT_CITATION_TEXT_MAX_LENGTH)
    score: float = Field(allow_inf_nan=False)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    page_number: int | None = Field(default=None, ge=1)
    section_title: str | None = Field(
        default=None,
        max_length=DOCUMENT_TITLE_MAX_LENGTH,
    )


class ChatQueryResponse(BaseModel):
    conversation_id: UUID
    answer: str = Field(max_length=CHAT_ANSWER_MAX_LENGTH)
    citations: list[Citation] = Field(max_length=CHAT_CITATION_LIMIT)
    suggested_questions: list[str]


def normalize_legacy_chat_scope(value) -> dict:
    if not isinstance(value, dict):
        return {}

    document_ids = []
    raw_document_ids = value.get("document_ids")
    if isinstance(raw_document_ids, list):
        for item in raw_document_ids[:CHAT_SCOPE_DOCUMENT_LIMIT]:
            try:
                document_ids.append(str(UUID(str(item))))
            except (TypeError, ValueError):
                continue

    tags = []
    raw_tags = value.get("tags")
    if isinstance(raw_tags, list):
        tags = [
            item.strip()[:TAG_NAME_MAX_LENGTH]
            for item in raw_tags
            if isinstance(item, str) and item.strip()
        ][:CHAT_SCOPE_TAG_LIMIT]

    source_types = []
    raw_source_types = value.get("source_types")
    if isinstance(raw_source_types, list):
        for item in raw_source_types[:CHAT_SCOPE_SOURCE_TYPE_LIMIT]:
            try:
                source_types.append(DocumentSourceType(item).value)
            except (TypeError, ValueError):
                continue

    recent_days = None
    raw_recent_days = value.get("recent_days")
    if isinstance(raw_recent_days, bool):
        recent_days = None
    elif isinstance(raw_recent_days, int) and 1 <= raw_recent_days <= 365:
        recent_days = raw_recent_days
    elif isinstance(raw_recent_days, float) and raw_recent_days.is_integer():
        candidate = int(raw_recent_days)
        if 1 <= candidate <= 365:
            recent_days = candidate
    elif isinstance(raw_recent_days, str) and raw_recent_days.strip().isdigit():
        candidate = int(raw_recent_days.strip())
        if 1 <= candidate <= 365:
            recent_days = candidate

    return {
        "document_ids": document_ids,
        "tags": tags,
        "source_types": source_types,
        "recent_days": recent_days,
    }


class ConversationRead(BaseModel):
    id: UUID
    title: str
    scope: ChatScope = Field(
        validation_alias=AliasChoices("scope_preview", "scope"),
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_validator("scope", mode="before")
    @classmethod
    def normalize_historical_scope(cls, value):
        return normalize_legacy_chat_scope(value)


class ConversationListItem(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationListResponse(BaseModel):
    items: list[ConversationListItem]
    total: int
    page: int
    page_size: int


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)

    model_config = ConfigDict(str_strip_whitespace=True)


class MessageRead(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str = Field(
        max_length=MESSAGE_LIST_CONTENT_PREVIEW_MAX_LENGTH,
        validation_alias="content_preview",
    )
    content_truncated: bool
    citations: list[Citation] = Field(
        max_length=CHAT_CITATION_LIMIT,
        validation_alias="citations_preview",
    )
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_validator("citations", mode="before")
    @classmethod
    def discard_invalid_historical_citations(cls, value):
        if not isinstance(value, list):
            return []
        valid: list[Citation] = []
        for item in value[:CHAT_CITATION_LIMIT]:
            try:
                valid.append(Citation.model_validate(item))
            except (TypeError, ValueError, ValidationError):
                continue
        return valid


class MessageListResponse(BaseModel):
    items: list[MessageRead]
    total: int
    page: int
    page_size: int


class MessageScanResponse(BaseModel):
    items: list[MessageRead]
    next_cursor: str | None = None
