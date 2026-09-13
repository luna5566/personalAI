from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import authenticated_user_id
from app.core.config import settings
from app.core.security import create_access_token, decode_access_token


def _credentials(user_id, session_id, **token_options):
    return HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=create_access_token(
            user_id,
            session_id,
            **token_options,
        ),
    )


class AuthenticatedSession:
    def __init__(
        self,
        *,
        user_id,
        session_id,
        session_user_id=None,
        session_expires_at=None,
        user_exists=True,
        session_exists=True,
    ) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.session_user_id = session_user_id or user_id
        self.session_expires_at = session_expires_at or (
            datetime.now(UTC) + timedelta(minutes=5)
        )
        self.user_exists = user_exists
        self.session_exists = session_exists
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        row = (
            SimpleNamespace(expires_at=self.session_expires_at)
            if self.session_exists
            and self.user_exists
            and self.session_user_id == self.user_id
            else None
        )
        return SimpleNamespace(one_or_none=lambda: row)


def test_missing_bearer_token_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        authenticated_user_id(None, None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


def test_invalid_bearer_token_is_rejected() -> None:
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid")

    with pytest.raises(HTTPException) as exc_info:
        authenticated_user_id(credentials, None)

    assert exc_info.value.status_code == 401


def test_valid_bearer_token_returns_subject() -> None:
    user_id = uuid4()
    session_id = uuid4()
    credentials = _credentials(user_id, session_id)

    assert authenticated_user_id(
        credentials,
        AuthenticatedSession(user_id=user_id, session_id=session_id),
    ) == user_id


def test_authentication_uses_one_narrow_session_user_join() -> None:
    user_id = uuid4()
    session_id = uuid4()
    db = AuthenticatedSession(user_id=user_id, session_id=session_id)

    assert authenticated_user_id(_credentials(user_id, session_id), db) == user_id

    compiled = db.statement.compile()
    select_clause = str(compiled).split("FROM auth_sessions", maxsplit=1)[0]
    sql = str(compiled)
    assert "auth_sessions.expires_at" in select_clause
    assert "JOIN users" in sql
    for column in (
        "auth_sessions.client_name",
        "auth_sessions.created_at",
        "users.email",
        "users.password_hash",
        "users.name",
        "users.avatar_url",
    ):
        assert column not in select_clause


def test_token_for_missing_user_is_rejected() -> None:
    user_id = uuid4()
    session_id = uuid4()
    credentials = _credentials(user_id, session_id)

    with pytest.raises(HTTPException) as exc_info:
        authenticated_user_id(
            credentials,
            AuthenticatedSession(
                user_id=user_id,
                session_id=session_id,
                user_exists=False,
            ),
        )

    assert exc_info.value.status_code == 401


def test_token_without_active_session_is_rejected() -> None:
    user_id = uuid4()
    session_id = uuid4()

    with pytest.raises(HTTPException) as exc_info:
        authenticated_user_id(
            _credentials(user_id, session_id),
            AuthenticatedSession(
                user_id=user_id,
                session_id=session_id,
                session_exists=False,
            ),
        )

    assert exc_info.value.status_code == 401


def test_token_for_another_sessions_user_is_rejected() -> None:
    user_id = uuid4()
    session_id = uuid4()

    with pytest.raises(HTTPException) as exc_info:
        authenticated_user_id(
            _credentials(user_id, session_id),
            AuthenticatedSession(
                user_id=user_id,
                session_id=session_id,
                session_user_id=uuid4(),
            ),
        )

    assert exc_info.value.status_code == 401


def test_database_session_expiration_is_enforced() -> None:
    user_id = uuid4()
    session_id = uuid4()

    with pytest.raises(HTTPException) as exc_info:
        authenticated_user_id(
            _credentials(user_id, session_id),
            AuthenticatedSession(
                user_id=user_id,
                session_id=session_id,
                session_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            ),
        )

    assert exc_info.value.status_code == 401


def test_access_token_uses_configured_expiration(monkeypatch) -> None:
    user_id = uuid4()
    session_id = uuid4()
    issued_after = datetime.now(UTC)
    monkeypatch.setattr(settings, "access_token_expire_minutes", 15)

    token = create_access_token(user_id, session_id)
    payload = jwt.decode(
        token,
        settings.auth_secret_key,
        algorithms=["HS256"],
        audience=settings.auth_token_audience,
        issuer=settings.auth_token_issuer,
    )

    expires_at = datetime.fromtimestamp(payload["exp"], UTC)
    assert payload["sub"] == str(user_id)
    assert payload["jti"] == str(session_id)
    assert payload["iss"] == settings.auth_token_issuer
    assert payload["aud"] == settings.auth_token_audience
    assert payload["token_type"] == "access"
    assert issued_after + timedelta(minutes=15) - timedelta(seconds=1) <= expires_at
    assert expires_at <= datetime.now(UTC) + timedelta(minutes=15)


def test_expired_bearer_token_is_rejected_before_user_lookup() -> None:
    now = datetime.now(UTC)
    token = create_access_token(
        uuid4(),
        uuid4(),
        issued_at=now - timedelta(minutes=2),
        expires_at=now - timedelta(seconds=31),
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    class UnexpectedUserSession:
        def get(self, model, requested_user_id):
            raise AssertionError("expired tokens must not query the user")

    with pytest.raises(HTTPException) as exc_info:
        authenticated_user_id(credentials, UnexpectedUserSession())

    assert exc_info.value.status_code == 401
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_legacy_token_without_session_claims_is_rejected() -> None:
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        settings.auth_secret_key,
        algorithm="HS256",
    )

    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_access_token(token)


def test_wrong_audience_and_token_type_are_rejected() -> None:
    user_id = uuid4()
    session_id = uuid4()
    now = datetime.now(UTC)
    base_payload = {
        "sub": str(user_id),
        "jti": str(session_id),
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "iss": settings.auth_token_issuer,
        "aud": "wrong-audience",
        "token_type": "access",
    }
    wrong_audience = jwt.encode(
        base_payload,
        settings.auth_secret_key,
        algorithm="HS256",
    )
    wrong_type = jwt.encode(
        {
            **base_payload,
            "aud": settings.auth_token_audience,
            "token_type": "refresh",
        },
        settings.auth_secret_key,
        algorithm="HS256",
    )

    with pytest.raises(jwt.InvalidAudienceError):
        decode_access_token(wrong_audience)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(wrong_type)
