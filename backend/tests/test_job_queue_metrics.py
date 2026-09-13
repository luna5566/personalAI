from prometheus_client import REGISTRY

from app.core.config import settings
from app.workers import job_recovery


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeQueueDepthSession:
    def __init__(self, rows):
        self._rows = rows
        self.statements = []

    def execute(self, statement, *args):
        self.statements.append(statement)
        return _RowsResult(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _sample(status: str):
    return REGISTRY.get_sample_value("job_queue_depth", {"status": status})


def test_update_job_queue_depth_sets_all_statuses_and_ignores_unknown() -> None:
    session = FakeQueueDepthSession(
        [
            (job_recovery.JobStatus.PENDING.value, 2),
            (job_recovery.JobStatus.RUNNING.value, 1),
            ("mystery_status", 99),
        ]
    )

    job_recovery.update_job_queue_depth(session)

    assert _sample("pending") == 2.0
    assert _sample("running") == 1.0
    for status in ("cancel_requested", "cancelled", "success", "failed"):
        assert _sample(status) == 0.0
    assert len(session.statements) == 1


def test_record_job_queue_depth_uses_session_and_applies_counts(monkeypatch) -> None:
    session = FakeQueueDepthSession([(job_recovery.JobStatus.PENDING.value, 5)])
    monkeypatch.setattr(job_recovery, "SessionLocal", lambda: session)

    job_recovery.record_job_queue_depth()

    assert _sample("pending") == 5.0


def test_record_job_queue_depth_skips_when_metrics_disabled(monkeypatch) -> None:
    previous = settings.metrics_enabled
    settings.metrics_enabled = False
    try:

        def _boom():
            raise AssertionError("metrics disabled should not open a session")

        monkeypatch.setattr(job_recovery, "SessionLocal", _boom)
        job_recovery.record_job_queue_depth()
    finally:
        settings.metrics_enabled = previous


def test_record_job_queue_depth_swallows_database_errors(monkeypatch) -> None:
    class BrokenSession:
        def __enter__(self):
            raise RuntimeError("database unavailable")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(job_recovery, "SessionLocal", BrokenSession)

    job_recovery.record_job_queue_depth()

    assert _sample("pending") is not None
