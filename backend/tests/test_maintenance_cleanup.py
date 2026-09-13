from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.models.job import Job
from app.services import maintenance_service


class MaintenanceSession:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.statements = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def scalar(self, statement):
        return self.now

    def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(rowcount=len(self.statements))

    def commit(self):
        self.commits += 1


def test_cleanup_deletes_bounded_oldest_rows_with_shared_cutoffs(
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    db = MaintenanceSession(now)
    timeouts = []
    monkeypatch.setattr(maintenance_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        maintenance_service,
        "set_local_statement_timeout",
        lambda session, seconds: timeouts.append((session, seconds)),
    )
    monkeypatch.setattr(
        maintenance_service.settings,
        "maintenance_cleanup_batch_size",
        1000,
    )
    monkeypatch.setattr(
        maintenance_service.settings,
        "auth_login_attempt_retention_seconds",
        3600,
    )
    monkeypatch.setattr(
        maintenance_service.settings,
        "auth_registration_attempt_retention_seconds",
        86400,
    )
    monkeypatch.setattr(
        maintenance_service.settings,
        "job_retention_days",
        30,
    )
    monkeypatch.setattr(
        maintenance_service.settings,
        "job_recovery_statement_timeout_seconds",
        1.25,
    )

    result = maintenance_service.purge_expired_data()

    assert result == maintenance_service.MaintenanceCleanupResult(1, 2, 3)
    assert timeouts == [(db, 1.25)]
    assert db.commits == 1
    assert len(db.statements) == 3

    compiled = [
        statement.compile(dialect=postgresql.dialect())
        for statement in db.statements
    ]
    sql = [str(statement) for statement in compiled]
    assert "WITH expired_auth_sessions AS" in sql[0]
    assert "DELETE FROM auth_sessions" in sql[0]
    assert "WITH expired_auth_login_attempts AS" in sql[1]
    assert "DELETE FROM auth_login_attempts" in sql[1]
    assert "WITH expired_jobs AS" in sql[2]
    assert "DELETE FROM jobs" in sql[2]
    for statement, params in zip(sql, (item.params for item in compiled)):
        assert "ORDER BY" in statement
        assert "LIMIT" in statement
        assert "FOR UPDATE SKIP LOCKED" in statement
        assert params["param_1"] == 1000

    assert compiled[0].params["expires_at_1"] == now
    assert compiled[1].params["updated_at_1"] == now - timedelta(days=1)
    assert compiled[2].params["updated_at_1"] == now - timedelta(days=30)
    assert set(compiled[2].params["status_1"]) == set(
        maintenance_service.TERMINAL_JOB_STATUSES
    )


def test_zero_batch_skips_database_work(monkeypatch) -> None:
    monkeypatch.setattr(
        maintenance_service,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("database opened")),
    )

    assert maintenance_service.purge_expired_data(batch_size=0) == (
        maintenance_service.MaintenanceCleanupResult(0, 0, 0)
    )


def test_jobs_have_maintenance_ordering_index() -> None:
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in Job.__table__.indexes
    }

    assert indexes["ix_jobs_updated_at_id"] == ("updated_at", "id")
