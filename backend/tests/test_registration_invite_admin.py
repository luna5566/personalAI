from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import authenticated_user_id, db_session
from app.api.routes.registration_invites import router
from app.core.config import settings
from app.schemas.registration_invite import (
    RegistrationInviteCreatedRead,
    RegistrationInvitePageRead,
    RegistrationInviteStatus,
)
from app.services import registration_invite_admin_service


class ScalarRows:
    def __init__(self, values) -> None:
        self.values = values

    def all(self):
        return self.values


class InviteListSession:
    def __init__(self, invites) -> None:
        self.invites = invites
        self.scalar_statement = None
        self.scalars_statement = None

    def scalar(self, statement):
        self.scalar_statement = statement
        return len(self.invites)

    def scalars(self, statement):
        self.scalars_statement = statement
        return ScalarRows(self.invites)


class InviteRevokeSession:
    def __init__(self, invite) -> None:
        self.invite = invite
        self.commits = 0

    def scalar(self, statement):
        return self.invite

    def commit(self):
        self.commits += 1


def _invite(
    *,
    used=False,
    expired=False,
    revoked=False,
):
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1)
        if expired
        else now + timedelta(hours=1),
        used_at=now - timedelta(minutes=10) if used else None,
        revoked_at=now - timedelta(minutes=5) if revoked else None,
    )


def test_registration_invite_management_is_admin_only() -> None:
    with pytest.raises(PermissionError, match="管理员"):
        registration_invite_admin_service.list_registration_invites(
            object(),
            user_id=uuid4(),
            page=1,
            page_size=20,
        )


def test_invite_list_computes_all_statuses_and_paginates() -> None:
    db = InviteListSession(
        [
            _invite(),
            _invite(used=True),
            _invite(expired=True),
            _invite(revoked=True),
        ]
    )

    page = registration_invite_admin_service.list_registration_invites(
        db,
        user_id=settings.runtime_settings_admin_user_id,
        page=2,
        page_size=2,
    )

    assert [item.status for item in page.items] == [
        RegistrationInviteStatus.ACTIVE,
        RegistrationInviteStatus.USED,
        RegistrationInviteStatus.EXPIRED,
        RegistrationInviteStatus.REVOKED,
    ]
    assert page.total == 4
    assert page.page == 2
    assert page.page_size == 2
    params = db.scalars_statement.compile().params
    assert params["param_1"] == 2
    assert params["param_2"] == 2


def test_active_filter_excludes_used_revoked_and_expired_rows() -> None:
    db = InviteListSession([])

    registration_invite_admin_service.list_registration_invites(
        db,
        user_id=settings.runtime_settings_admin_user_id,
        page=1,
        page_size=20,
        invite_status=RegistrationInviteStatus.ACTIVE,
    )

    sql = str(db.scalars_statement)
    assert "used_at IS NULL" in sql
    assert "revoked_at IS NULL" in sql
    assert "expires_at >" in sql


def test_revoke_active_invite_and_repeat_idempotently() -> None:
    invite = _invite()
    db = InviteRevokeSession(invite)

    registration_invite_admin_service.revoke_registration_invite(
        db,
        user_id=settings.runtime_settings_admin_user_id,
        invite_id=invite.id,
    )
    first_revoked_at = invite.revoked_at
    registration_invite_admin_service.revoke_registration_invite(
        db,
        user_id=settings.runtime_settings_admin_user_id,
        invite_id=invite.id,
    )

    assert first_revoked_at is not None
    assert invite.revoked_at == first_revoked_at
    assert db.commits == 2


@pytest.mark.parametrize("invite", [_invite(used=True), _invite(expired=True)])
def test_used_or_expired_invite_cannot_be_revoked(invite) -> None:
    db = InviteRevokeSession(invite)

    with pytest.raises(
        registration_invite_admin_service.RegistrationInviteNotRevocableError,
        match="不能撤销",
    ):
        registration_invite_admin_service.revoke_registration_invite(
            db,
            user_id=settings.runtime_settings_admin_user_id,
            invite_id=invite.id,
        )

    assert db.commits == 0


def test_unknown_invite_cannot_be_revoked() -> None:
    with pytest.raises(
        registration_invite_admin_service.RegistrationInviteNotFoundError,
        match="不存在",
    ):
        registration_invite_admin_service.revoke_registration_invite(
            InviteRevokeSession(None),
            user_id=settings.runtime_settings_admin_user_id,
            invite_id=uuid4(),
        )


def test_list_route_returns_page_without_cache(monkeypatch) -> None:
    app = FastAPI(debug=False)
    app.include_router(router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_user_id] = (
        lambda: settings.runtime_settings_admin_user_id
    )
    captured = []

    def list_invites(db, *, user_id, page, page_size, invite_status):
        captured.append((user_id, page, page_size, invite_status))
        return RegistrationInvitePageRead(
            items=[],
            total=0,
            page=page,
            page_size=page_size,
        )

    monkeypatch.setattr(
        registration_invite_admin_service,
        "list_registration_invites",
        list_invites,
    )
    response = TestClient(app).get(
        "/auth/registration-invites?page=2&page_size=10&status=active"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "items": [],
        "total": 0,
        "page": 2,
        "page_size": 10,
    }
    assert captured == [
        (
            settings.runtime_settings_admin_user_id,
            2,
            10,
            RegistrationInviteStatus.ACTIVE,
        )
    ]


def test_create_route_returns_raw_code_once_without_cache(monkeypatch) -> None:
    app = FastAPI(debug=False)
    app.include_router(router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_user_id] = (
        lambda: settings.runtime_settings_admin_user_id
    )
    now = datetime.now(UTC)

    def create_invite(db, *, user_id, valid_hours):
        assert valid_hours == 24
        return RegistrationInviteCreatedRead(
            id=uuid4(),
            code="raw-code-shown-once",
            status=RegistrationInviteStatus.ACTIVE,
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )

    monkeypatch.setattr(
        registration_invite_admin_service,
        "create_managed_registration_invite",
        create_invite,
    )
    response = TestClient(app).post(
        "/auth/registration-invites",
        json={"valid_hours": 24},
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "raw-code-shown-once"
    assert "code_hash" not in response.text


def test_non_admin_route_returns_403() -> None:
    app = FastAPI(debug=False)
    app.include_router(router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_user_id] = uuid4

    response = TestClient(app).get("/auth/registration-invites")

    assert response.status_code == 403
    assert response.json() == {"detail": "只有管理员可以管理注册邀请码"}


def test_revoke_route_maps_conflict(monkeypatch) -> None:
    app = FastAPI(debug=False)
    app.include_router(router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_user_id] = (
        lambda: settings.runtime_settings_admin_user_id
    )

    def conflict(db, *, user_id, invite_id):
        raise registration_invite_admin_service.RegistrationInviteNotRevocableError(
            "已使用或已过期的邀请码不能撤销"
        )

    monkeypatch.setattr(
        registration_invite_admin_service,
        "revoke_registration_invite",
        conflict,
    )
    response = TestClient(app).delete(f"/auth/registration-invites/{uuid4()}")

    assert response.status_code == 409
    assert response.json() == {"detail": "已使用或已过期的邀请码不能撤销"}
