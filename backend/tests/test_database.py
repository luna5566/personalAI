from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core import database
from app.core.config import Settings


def test_database_engine_uses_bounded_connect_and_pool_waits(monkeypatch) -> None:
    captured = {}
    expected_engine = object()

    def create_engine(url, **options):
        captured["url"] = url
        captured["options"] = options
        return expected_engine

    monkeypatch.setattr(database, "create_engine", create_engine)
    monkeypatch.setattr(database.settings, "database_connect_timeout_seconds", 7)
    monkeypatch.setattr(database.settings, "database_pool_size", 3)
    monkeypatch.setattr(database.settings, "database_pool_max_overflow", 4)
    monkeypatch.setattr(database.settings, "database_pool_timeout_seconds", 1.5)
    monkeypatch.setattr(database.settings, "database_statement_timeout_seconds", 12.5)

    created = database.create_database_engine()

    assert created is expected_engine
    assert captured["url"] == database.settings.database_url
    assert captured["options"] == {
        "pool_pre_ping": True,
        "pool_size": 3,
        "max_overflow": 4,
        "pool_timeout": 1.5,
        "connect_args": {
            "connect_timeout": 7,
            "options": "-c statement_timeout=12500",
        },
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_connect_timeout_seconds", 0),
        ("database_pool_size", 0),
        ("database_pool_max_overflow", -1),
        ("database_pool_timeout_seconds", 0),
        ("database_statement_timeout_seconds", 0),
        ("database_health_statement_timeout_seconds", 0),
        ("database_retry_after_seconds", 0),
    ],
)
def test_database_timeouts_must_be_positive(field, value) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_database_pool_snapshot_normalizes_and_detects_saturation(monkeypatch) -> None:
    class Pool:
        def size(self):
            return 3

        def checkedin(self):
            return 0

        def checkedout(self):
            return 7

        def overflow(self):
            return -1

    monkeypatch.setattr(database, "engine", SimpleNamespace(pool=Pool()))
    monkeypatch.setattr(database.settings, "database_pool_max_overflow", 4)

    snapshot = database.database_pool_snapshot()

    assert snapshot == database.DatabasePoolSnapshot(
        pool_size=3,
        max_overflow=4,
        capacity=7,
        checked_in=0,
        checked_out=7,
        overflow=0,
        utilization_percent=100.0,
        saturated=True,
    )


def test_application_sessions_keep_loaded_values_after_stage_commits() -> None:
    assert database.SessionLocal.kw["expire_on_commit"] is False


def test_hnsw_search_options_are_transaction_local() -> None:
    class Session:
        def __init__(self) -> None:
            self.calls = []

        def execute(self, statement, parameters):
            self.calls.append((statement, parameters))

    db = Session()

    database.set_local_hnsw_search_options(
        db,
        ef_search=123,
        max_scan_tuples=45678,
    )

    assert len(db.calls) == 1
    statement, parameters = db.calls[0]
    sql = str(statement)
    assert "hnsw.iterative_scan" in sql
    assert "'strict_order'" in sql
    assert sql.count("true") == 3
    assert parameters == {
        "ef_search": "123",
        "max_scan_tuples": "45678",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hnsw_ef_search", 0),
        ("hnsw_ef_search", 1001),
        ("hnsw_max_scan_tuples", 0),
        ("hnsw_max_scan_tuples", 1_000_001),
    ],
)
def test_hnsw_search_options_stay_within_bounds(field, value) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
