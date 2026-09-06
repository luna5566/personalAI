import hashlib

from argon2 import PasswordHasher, Type
import pytest

from app.core.security import (
    ARGON2_MEMORY_COST_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    LEGACY_PBKDF2_ITERATIONS,
    hash_password,
    password_needs_rehash,
    verify_password,
)


def _legacy_hash(password: str, salt: str = "0123456789abcdef" * 2) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        LEGACY_PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def test_new_password_hash_uses_configured_argon2id() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert password_hash.startswith(
        "$argon2id$v=19$"
        f"m={ARGON2_MEMORY_COST_KIB},t={ARGON2_TIME_COST},p={ARGON2_PARALLELISM}$"
    )
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong password", password_hash)
    assert not password_needs_rehash(password_hash)


def test_legacy_pbkdf2_password_remains_valid_but_needs_rehash() -> None:
    password_hash = _legacy_hash("legacy-password")

    assert verify_password("legacy-password", password_hash)
    assert not verify_password("wrong-password", password_hash)
    assert password_needs_rehash(password_hash)


def test_argon2_hash_with_old_cost_needs_rehash() -> None:
    old_hasher = PasswordHasher(
        time_cost=1,
        memory_cost=8 * 1024,
        parallelism=1,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )
    password_hash = old_hasher.hash("password")

    assert verify_password("password", password_hash)
    assert password_needs_rehash(password_hash)


@pytest.mark.parametrize(
    "password_hash",
    [
        "",
        "not-a-password-hash",
        "$argon2id$malformed",
        "pbkdf2_sha256$missing-digest",
        "pbkdf2_sha256$salt$not-hex",
        "pbkdf2_sha256$salt$00",
    ],
)
def test_malformed_password_hash_is_rejected(password_hash: str) -> None:
    assert not verify_password("password", password_hash)
    assert password_needs_rehash(password_hash)
