from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class RegistrationInviteStatus(str, Enum):
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


class RegistrationInviteCreate(BaseModel):
    valid_hours: int = Field(default=168, ge=1, le=8760)


class RegistrationInviteRead(BaseModel):
    id: UUID
    status: RegistrationInviteStatus
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None


class RegistrationInviteCreatedRead(RegistrationInviteRead):
    code: str


class RegistrationInvitePageRead(BaseModel):
    items: list[RegistrationInviteRead]
    total: int
    page: int
    page_size: int
