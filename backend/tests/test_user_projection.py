from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.request_limits import USER_AVATAR_URL_MAX_LENGTH
from app.schemas.auth import UserRead
from app.services import auth_service


def _select_clause(statement) -> tuple[str, list[object]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return (
        str(compiled).split("FROM users", maxsplit=1)[0],
        list(compiled.params.values()),
    )


def test_public_user_projection_bounds_avatar_and_excludes_password() -> None:
    select_clause, values = _select_clause(auth_service._user_public_statement())

    assert "left(users.avatar_url" in select_clause
    assert USER_AVATAR_URL_MAX_LENGTH in values
    for column in ("id", "email", "name", "created_at"):
        assert f"users.{column}" in select_clause
    assert "users.password_hash" not in select_clause
    assert "users.avatar_url AS avatar_url" not in select_clause


def test_auth_user_projection_loads_password_but_not_raw_avatar() -> None:
    select_clause, values = _select_clause(auth_service._user_auth_statement())

    assert "users.password_hash" in select_clause
    assert "left(users.avatar_url" in select_clause
    assert USER_AVATAR_URL_MAX_LENGTH in values
    assert "users.avatar_url AS avatar_url" not in select_clause


def test_account_deletion_user_lock_excludes_public_profile_payload() -> None:
    select_clause, _ = _select_clause(auth_service._user_deletion_statement())

    for column in ("id", "email", "password_hash"):
        assert f"users.{column}" in select_clause
    for column in ("name", "avatar_url", "created_at", "updated_at"):
        assert f"users.{column}" not in select_clause


def test_user_read_bounds_legacy_avatar_in_memory() -> None:
    now = datetime.now(timezone.utc)
    source = SimpleNamespace(
        id=uuid4(),
        email="user@example.com",
        name="用户",
        avatar_url="x" * (USER_AVATAR_URL_MAX_LENGTH + 1),
        created_at=now,
    )

    payload = auth_service._user_read(source).model_dump(mode="json")

    assert len(payload["avatar_url"]) == USER_AVATAR_URL_MAX_LENGTH


def test_user_read_schema_rejects_avatar_over_public_limit() -> None:
    with pytest.raises(ValidationError):
        UserRead(
            id=uuid4(),
            email="user@example.com",
            avatar_url="x" * (USER_AVATAR_URL_MAX_LENGTH + 1),
            created_at=datetime.now(timezone.utc),
        )
