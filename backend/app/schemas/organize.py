from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.request_limits import (
    ORGANIZE_RESULT_MAX_LENGTH,
    TAG_NAME_MAX_LENGTH,
)


class DocumentOrganizeMode(str, Enum):
    SUMMARY = "summary"
    OUTLINE = "outline"
    KEY_POINTS = "key_points"
    ACTION_ITEMS = "action_items"


class CollectionOrganizeMode(str, Enum):
    THEMES = "themes"
    CONNECTIONS = "connections"
    ARTICLE_OUTLINE = "article_outline"
    STUDY_PLAN = "study_plan"


class OrganizeDocumentRequest(BaseModel):
    document_id: UUID
    mode: DocumentOrganizeMode = DocumentOrganizeMode.SUMMARY
    save_as_note: bool = False


class OrganizeCollectionRequest(BaseModel):
    document_ids: list[UUID] = Field(default_factory=list, max_length=20)
    tag: str | None = Field(
        default=None,
        min_length=1,
        max_length=TAG_NAME_MAX_LENGTH,
    )
    mode: CollectionOrganizeMode = CollectionOrganizeMode.THEMES
    save_as_note: bool = False

    model_config = ConfigDict(str_strip_whitespace=True)


class OrganizeResponse(BaseModel):
    mode: str
    result: str = Field(max_length=ORGANIZE_RESULT_MAX_LENGTH)
    source_document_ids: list[UUID]
    saved_document_id: UUID | None = None


class OrganizeResultSaveRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    result: str = Field(
        min_length=1,
        max_length=ORGANIZE_RESULT_MAX_LENGTH,
    )
    source_document_ids: list[UUID] = Field(min_length=1, max_length=100)

    model_config = ConfigDict(str_strip_whitespace=True)


class OrganizeResultSaveResponse(BaseModel):
    saved_document_id: UUID
