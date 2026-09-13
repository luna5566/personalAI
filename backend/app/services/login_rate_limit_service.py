import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from uuid import UUID

from sqlalchemy import and_, case, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.auth_login_attempt import AuthLoginAttempt


@dataclass(frozen=True)
class LoginRateLimitPolicy:
    account_max_failures: int
    client_max_failures: int
    window_seconds: int
    lockout_seconds: int


@dataclass(frozen=True)
class RegistrationRateLimitPolicy:
    client_max_attempts: int
    window_seconds: int
    lockout_seconds: int


@dataclass(frozen=True)
class AiUserRateLimitPolicy:
    max_requests: int
    window_seconds: int
    lockout_seconds: int


@dataclass(frozen=True)
class RateLimitRule:
    scope_hash: str
    block_threshold: int
    window_seconds: int
    lockout_seconds: int


def login_scope_hash(scope: str, value: str, secret_key: str) -> str:
    message = f"{scope}:{value}".encode()
    return hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


class AuthRateLimitStore:
    def check_retry_after(
        self,
        db: Session,
        *,
        scope_hashes: list[str],
    ) -> int | None:
        now = self._database_now(db)
        blocked_values = db.scalars(
            select(AuthLoginAttempt.blocked_until).where(
                AuthLoginAttempt.scope_hash.in_(scope_hashes)
            )
        ).all()
        return self._maximum_retry_after(blocked_values, now)

    def record(
        self,
        db: Session,
        *,
        rules: list[RateLimitRule],
    ) -> int | None:
        now = self._database_now(db)

        blocked_values: list[datetime | None] = []
        for rule in rules:
            statement = self._upsert(rule=rule, now=now)
            blocked_values.append(db.scalar(statement))
        db.commit()
        return self._maximum_retry_after(blocked_values, now)

    @staticmethod
    def clear_scope(db: Session, *, scope_hash: str) -> None:
        db.execute(
            delete(AuthLoginAttempt).where(
                AuthLoginAttempt.scope_hash == scope_hash
            )
        )

    @staticmethod
    def _upsert(*, rule: RateLimitRule, now: datetime):
        table = AuthLoginAttempt.__table__
        window_cutoff = now - timedelta(seconds=rule.window_seconds)
        lock_until = now + timedelta(seconds=rule.lockout_seconds)
        active_block = and_(
            table.c.blocked_until.is_not(None),
            table.c.blocked_until > now,
        )
        expired_window = table.c.window_started_at <= window_cutoff
        next_failed_attempts = case(
            (active_block, table.c.failed_attempts),
            (expired_window, 1),
            else_=table.c.failed_attempts + 1,
        )
        next_window_started_at = case(
            (active_block, table.c.window_started_at),
            (expired_window, now),
            else_=table.c.window_started_at,
        )
        next_blocked_until = case(
            (active_block, table.c.blocked_until),
            (
                expired_window,
                lock_until if rule.block_threshold <= 1 else None,
            ),
            (
                table.c.failed_attempts + 1 >= rule.block_threshold,
                lock_until,
            ),
            else_=None,
        )
        initial_blocked_until = (
            lock_until if rule.block_threshold <= 1 else None
        )

        statement = insert(table).values(
            scope_hash=rule.scope_hash,
            failed_attempts=1,
            window_started_at=now,
            blocked_until=initial_blocked_until,
            updated_at=now,
        )
        return statement.on_conflict_do_update(
            index_elements=[table.c.scope_hash],
            set_={
                "failed_attempts": next_failed_attempts,
                "window_started_at": next_window_started_at,
                "blocked_until": next_blocked_until,
                "updated_at": now,
            },
        ).returning(table.c.blocked_until)

    @staticmethod
    def _database_now(db: Session) -> datetime:
        now = db.scalar(select(func.now()))
        if not isinstance(now, datetime):
            raise RuntimeError("database did not return a timestamp")
        return now

    @staticmethod
    def _maximum_retry_after(
        blocked_values: list[datetime | None],
        now: datetime,
    ) -> int | None:
        retry_values = [
            max(ceil((blocked_until - now).total_seconds()), 1)
            for blocked_until in blocked_values
            if blocked_until is not None and blocked_until > now
        ]
        return max(retry_values, default=None)


class LoginRateLimiter:
    def __init__(
        self,
        *,
        secret_key: str,
        policy: LoginRateLimitPolicy,
        store: AuthRateLimitStore | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._policy = policy
        self._store = store or AuthRateLimitStore()

    def check_retry_after(
        self,
        db: Session,
        *,
        email: str,
        client_host: str | None,
    ) -> int | None:
        scope_limits = self._scope_limits(email, client_host)
        return self._store.check_retry_after(
            db,
            scope_hashes=[scope_hash for scope_hash, _ in scope_limits],
        )

    def record_failure(
        self,
        db: Session,
        *,
        email: str,
        client_host: str | None,
    ) -> int | None:
        return self._store.record(
            db,
            rules=[
                RateLimitRule(
                    scope_hash=scope_hash,
                    block_threshold=max_failures,
                    window_seconds=self._policy.window_seconds,
                    lockout_seconds=self._policy.lockout_seconds,
                )
                for scope_hash, max_failures in self._scope_limits(
                    email,
                    client_host,
                )
            ],
        )

    def clear_account_failures(self, db: Session, *, email: str) -> None:
        account_hash = login_scope_hash(
            "account",
            email.strip().casefold(),
            self._secret_key,
        )
        self._store.clear_scope(db, scope_hash=account_hash)

    def _scope_limits(
        self,
        email: str,
        client_host: str | None,
    ) -> list[tuple[str, int]]:
        scopes = [
            (
                login_scope_hash(
                    "account",
                    email.strip().casefold(),
                    self._secret_key,
                ),
                self._policy.account_max_failures,
            )
        ]
        normalized_client = client_host.strip().casefold() if client_host else ""
        if normalized_client:
            scopes.append(
                (
                    login_scope_hash("client", normalized_client, self._secret_key),
                    self._policy.client_max_failures,
                )
            )
        return scopes



class RegistrationRateLimiter:
    def __init__(
        self,
        *,
        secret_key: str,
        policy: RegistrationRateLimitPolicy,
        store: AuthRateLimitStore | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._policy = policy
        self._store = store or AuthRateLimitStore()

    def consume(self, db: Session, *, client_host: str | None) -> int | None:
        normalized_client = (
            client_host.strip().casefold() if client_host else "unknown"
        )
        scope_hash = login_scope_hash(
            "registration-client",
            normalized_client,
            self._secret_key,
        )
        return self._store.record(
            db,
            rules=[
                RateLimitRule(
                    scope_hash=scope_hash,
                    # The first N requests are allowed; request N + 1 blocks.
                    block_threshold=self._policy.client_max_attempts + 1,
                    window_seconds=self._policy.window_seconds,
                    lockout_seconds=self._policy.lockout_seconds,
                )
            ],
        )


login_rate_limiter = LoginRateLimiter(
    secret_key=settings.auth_secret_key,
    policy=LoginRateLimitPolicy(
        account_max_failures=settings.auth_login_account_max_failures,
        client_max_failures=settings.auth_login_client_max_failures,
        window_seconds=settings.auth_login_window_seconds,
        lockout_seconds=settings.auth_login_lockout_seconds,
    ),
)

registration_rate_limiter = RegistrationRateLimiter(
    secret_key=settings.auth_secret_key,
    policy=RegistrationRateLimitPolicy(
        client_max_attempts=settings.auth_registration_client_max_attempts,
        window_seconds=settings.auth_registration_window_seconds,
        lockout_seconds=settings.auth_registration_lockout_seconds,
    ),
)


class AiUserRateLimiter:
    """Shared per-user quota for chat query and organize endpoints."""

    def __init__(
        self,
        *,
        secret_key: str,
        policy: AiUserRateLimitPolicy,
        store: AuthRateLimitStore | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._policy = policy
        self._store = store or AuthRateLimitStore()

    def consume(self, db: Session, *, user_id: UUID) -> int | None:
        scope_hash = login_scope_hash(
            "ai-user",
            str(user_id),
            self._secret_key,
        )
        return self._store.record(
            db,
            rules=[
                RateLimitRule(
                    scope_hash=scope_hash,
                    # The first N requests are allowed; request N + 1 blocks.
                    block_threshold=self._policy.max_requests + 1,
                    window_seconds=self._policy.window_seconds,
                    lockout_seconds=self._policy.lockout_seconds,
                )
            ],
        )


ai_user_rate_limiter = AiUserRateLimiter(
    secret_key=settings.auth_secret_key,
    policy=AiUserRateLimitPolicy(
        max_requests=settings.ai_user_max_requests,
        window_seconds=settings.ai_user_window_seconds,
        lockout_seconds=settings.ai_user_lockout_seconds,
    ),
)
