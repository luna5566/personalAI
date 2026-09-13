from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.auth_registration_invite import AuthRegistrationInvite
from app.schemas.auth import UserRead, UserRegister
from app.services import auth_service
from app.services.registration_invite_service import (
    create_registration_invite,
    registration_invite_hash,
)


class FakeLimiter:
    def __init__(self) -> None:
        self.hosts = []

    def consume(self, db, *, client_host):
        self.hosts.append(client_host)
        return


class InviteLookupSession:
    def __init__(self, invite) -> None:
        self.invite = invite
        self.scalar_calls = 0

    def scalar(self, statement):
        self.scalar_calls += 1
        return self.invite


class InviteRegistrationSession:
    def __init__(self, invite) -> None:
        self.scalar_values = iter([invite, None])
        self.added = []
        self.flushes = 0
        self.commits = 0
        self.refreshes = 0

    def scalar(self, statement):
        return next(self.scalar_values)

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1

    def refresh(self, value):
        self.refreshes += 1


class InviteCreationSession:
    def __init__(self) -> None:
        self.added = []
        self.commits = 0
        self.refreshes = 0

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def refresh(self, value):
        self.refreshes += 1


def _payload(invite_code: str | None = "one-time-code") -> UserRegister:
    return UserRegister(
        email="invitee@example.com",
        password="secure-password",
        name="Invitee",
        invite_code=invite_code,
    )


def test_invite_hash_is_keyed_and_does_not_contain_raw_code() -> None:
    first = registration_invite_hash("  one-time-code  ", secret_key="secret-a")
    same = registration_invite_hash("one-time-code", secret_key="secret-a")
    other_key = registration_invite_hash("one-time-code", secret_key="secret-b")

    assert first == same
    assert first != other_key
    assert len(first) == 64
    assert "one-time-code" not in first


def test_create_invite_only_persists_hash_and_expiration() -> None:
    now = datetime(2026, 7, 17, 12, tzinfo=UTC)
    db = InviteCreationSession()

    created = create_registration_invite(
        db,
        valid_for=timedelta(hours=24),
        now=now,
        code="one-time-code",
    )

    assert created.code == "one-time-code"
    assert len(db.added) == 1
    invite = db.added[0]
    assert isinstance(invite, AuthRegistrationInvite)
    assert invite.code_hash == registration_invite_hash("one-time-code")
    assert invite.expires_at == now + timedelta(hours=24)
    assert invite.used_at is None
    assert db.commits == 1
    assert db.refreshes == 1


def test_registration_atomically_marks_valid_invite_used(monkeypatch) -> None:
    invite = SimpleNamespace(
        used_at=None,
        revoked_at=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db = InviteRegistrationSession(invite)
    limiter = FakeLimiter()
    expected_user = UserRead(
        id="00000000-0000-0000-0000-000000000001",
        email="invitee@example.com",
        name="Invitee",
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(auth_service, "hash_password", lambda password: "hash")
    monkeypatch.setattr(
        auth_service,
        "_issue_access_token",
        lambda *args, **kwargs: "access-token",
    )
    monkeypatch.setattr(auth_service, "_user_read", lambda user: expected_user)

    response = auth_service.register(
        db,
        _payload(),
        "192.0.2.10",
        limiter=limiter,
        invite_required=True,
    )

    assert response.access_token == "access-token"
    assert response.user == expected_user
    assert invite.used_at is not None
    assert invite.used_at.tzinfo is not None
    assert limiter.hosts == ["192.0.2.10"]
    assert db.flushes == 1
    assert db.commits == 1
    assert db.refreshes == 1


def test_missing_invite_is_rejected_after_rate_limit_before_lookup() -> None:
    db = InviteLookupSession(None)
    limiter = FakeLimiter()

    with pytest.raises(
        auth_service.RegistrationInviteInvalidError,
        match="邀请码无效或已过期",
    ):
        auth_service.register(
            db,
            _payload(None),
            "192.0.2.10",
            limiter=limiter,
            invite_required=True,
        )

    assert limiter.hosts == ["192.0.2.10"]
    assert db.scalar_calls == 0


@pytest.mark.parametrize(
    "invite",
    [
        SimpleNamespace(
            used_at=datetime.now(UTC),
            revoked_at=None,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        SimpleNamespace(
            used_at=None,
            revoked_at=None,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        ),
        SimpleNamespace(
            used_at=None,
            revoked_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        None,
    ],
)
def test_used_expired_revoked_or_unknown_invite_has_same_error(invite) -> None:
    db = InviteLookupSession(invite)

    with pytest.raises(
        auth_service.RegistrationInviteInvalidError,
        match="邀请码无效或已过期",
    ):
        auth_service._lock_valid_registration_invite(db, "one-time-code")
