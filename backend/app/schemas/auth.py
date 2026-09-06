from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.request_limits import USER_AVATAR_URL_MAX_LENGTH

PASSWORD_MAX_LENGTH = 1024


class AuthConfigRead(BaseModel):
    registration_enabled: bool
    invitation_required: bool


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=PASSWORD_MAX_LENGTH)
    name: str | None = Field(default=None, max_length=128)
    invite_code: str | None = Field(default=None, min_length=1, max_length=256)


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(min_length=6, max_length=PASSWORD_MAX_LENGTH)


class AccountDelete(BaseModel):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    confirmation: Literal["DELETE"]


class AuthSessionRead(BaseModel):
    id: UUID
    client_name: str | None = None
    created_at: datetime
    expires_at: datetime
    is_current: bool


class UserRead(BaseModel):
    id: UUID
    email: str = Field(max_length=255)
    name: str | None = Field(default=None, max_length=128)
    avatar_url: str | None = Field(
        default=None,
        max_length=USER_AVATAR_URL_MAX_LENGTH,
    )
    is_admin: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
