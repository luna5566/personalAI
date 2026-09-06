from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.request_limits import (
    DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH,
    DOCUMENT_LIST_SUMMARY_PREVIEW_MAX_LENGTH,
    DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH,
    DOCUMENT_SUMMARY_MAX_LENGTH,
    DOCUMENT_TAG_LIMIT,
    DOCUMENT_TITLE_MAX_LENGTH,
    NOTE_CONTENT_MAX_LENGTH,
    TAG_NAME_MAX_LENGTH,
)
from app.models.document import DocumentSourceType, DocumentStatus


DocumentTagName = Annotated[
    str,
    Field(min_length=1, max_length=TAG_NAME_MAX_LENGTH),
]


class NoteCreate(BaseModel):
    title: str | None = Field(
        default=None,
        max_length=DOCUMENT_TITLE_MAX_LENGTH,
    )
    content: str = Field(min_length=1, max_length=NOTE_CONTENT_MAX_LENGTH)
    tags: list[DocumentTagName] = Field(
        default_factory=list,
        max_length=DOCUMENT_TAG_LIMIT,
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class DocumentUpdate(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=DOCUMENT_TITLE_MAX_LENGTH,
    )
    tags: list[DocumentTagName] | None = Field(
        default=None,
        max_length=DOCUMENT_TAG_LIMIT,
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class DocumentRead(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    source_type: DocumentSourceType
    original_filename: str | None = None
    file_size: int | None = None
    mime_type: str | None = None
    content: str | None = Field(
        default=None,
        max_length=DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH,
    )
    content_source: str | None = None
    content_offset: int = Field(default=0, ge=0)
    content_length: int = Field(default=0, ge=0)
    content_truncated: bool = False
    summary: str | None = Field(
        default=None,
        max_length=DOCUMENT_SUMMARY_MAX_LENGTH,
    )
    status: DocumentStatus
    error_message: str | None = Field(
        default=None,
        max_length=DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH,
    )
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class DocumentListItem(BaseModel):
    id: UUID
    title: str
    source_type: DocumentSourceType
    summary: str | None = Field(
        default=None,
        max_length=DOCUMENT_LIST_SUMMARY_PREVIEW_MAX_LENGTH,
        validation_alias="summary_preview",
    )
    status: DocumentStatus
    error_message: str | None = Field(
        default=None,
        max_length=DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH,
        validation_alias="error_message_preview",
    )
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    total: int
    page: int
    page_size: int


class DocumentScanResponse(BaseModel):
    items: list[DocumentListItem]
    next_cursor: str | None = None


class DocumentStatsRead(BaseModel):
    total: int
    indexed: int
    processing: int
    failed: int
    cancelled: int
    storage_bytes: int


class DocumentUploadResponse(BaseModel):
    document_id: UUID
    job_id: UUID
    filename: str
    status: DocumentStatus


class RelatedDocumentRead(BaseModel):
    document_id: UUID
    title: str
    source_type: DocumentSourceType
    matched_text: str
    score: float
