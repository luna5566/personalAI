from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.request_limits import TAG_NAME_MAX_LENGTH


class TagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=TAG_NAME_MAX_LENGTH)
    color: str | None = Field(default=None, max_length=32)

    model_config = ConfigDict(str_strip_whitespace=True)


class TagRead(BaseModel):
    id: UUID
    name: str
    color: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TagScanResponse(BaseModel):
    items: list[TagRead]
    next_cursor: str | None = None
