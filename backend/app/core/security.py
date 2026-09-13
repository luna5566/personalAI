import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

LEGACY_PBKDF2_ITERATIONS = 210_000
ARGON2_TIME_COST = 2
ARGON2_MEMORY_COST_KIB = 19 * 1024
ARGON2_PARALLELISM = 1

_password_hasher = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST_KIB,
    parallelism=ARGON2_PARALLELISM,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    session_id: UUID
    issued_at: datetime
    expires_at: datetime


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("$argon2id$"):
        try:
            return _password_hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False

    return _verify_legacy_pbkdf2(password, password_hash)


def password_needs_rehash(password_hash: str) -> bool:
    if not password_hash.startswith("$argon2id$"):
        return True
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, VerificationError):
        return True


def _verify_legacy_pbkdf2(password: str, password_hash: str) -> bool:
    parts = password_hash.split("$")
    if len(parts) != 3 or parts[0] != "pbkdf2_sha256":
        return False
    _, salt, expected_hex = parts
    try:
        expected_digest = bytes.fromhex(expected_hex)
    except ValueError:
        return False
    if len(expected_digest) != hashlib.sha256().digest_size:
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        LEGACY_PBKDF2_ITERATIONS,
    )
    return hmac.compare_digest(digest, expected_digest)


def create_access_token(
    user_id: UUID,
    session_id: UUID,
    *,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> str:
    issued_at = issued_at or datetime.now(UTC)
    expires_at = expires_at or (
        issued_at + timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {
        "sub": str(user_id),
        "jti": str(session_id),
        "iat": issued_at,
        "exp": expires_at,
        "iss": settings.auth_token_issuer,
        "aud": settings.auth_token_audience,
        "token_type": "access",
    }
    return jwt.encode(payload, settings.auth_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> AccessTokenClaims:
    payload = jwt.decode(
        token,
        settings.auth_secret_key,
        algorithms=["HS256"],
        audience=settings.auth_token_audience,
        issuer=settings.auth_token_issuer,
        leeway=settings.auth_token_clock_skew_seconds,
        options={
            "require": [
                "sub",
                "jti",
                "iat",
                "exp",
                "iss",
                "aud",
                "token_type",
            ]
        },
    )
    if payload["token_type"] != "access":
        raise jwt.InvalidTokenError("invalid token type")
    return AccessTokenClaims(
        user_id=UUID(payload["sub"]),
        session_id=UUID(payload["jti"]),
        issued_at=datetime.fromtimestamp(payload["iat"], UTC),
        expires_at=datetime.fromtimestamp(payload["exp"], UTC),
    )
