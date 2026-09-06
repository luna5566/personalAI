from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.request_limits import (
    JOB_ERROR_MESSAGE_MAX_LENGTH,
    JOB_MESSAGE_MAX_LENGTH,
)
from app.models.job import JobStatus, JobType


class JobRead(BaseModel):
    id: UUID
    user_id: UUID
    document_id: UUID | None = None
    retry_of_job_id: UUID | None = None
    job_type: JobType
    status: JobStatus
    progress: int
    message: str | None = Field(default=None, max_length=JOB_MESSAGE_MAX_LENGTH)
    error_message: str | None = Field(
        default=None,
        max_length=JOB_ERROR_MESSAGE_MAX_LENGTH,
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobListResponse(BaseModel):
    items: list[JobRead]
    total: int
    page: int
    page_size: int
