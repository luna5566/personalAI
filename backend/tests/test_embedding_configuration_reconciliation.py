from types import SimpleNamespace
from uuid import uuid4

from app.models.embedding_configuration_state import EmbeddingConfigurationState
from app.models.job import JobType
from app.services import embedding_configuration_service


class ReconciliationSession:
    def __init__(self, state, scalar_results=()) -> None:
        self.state = state
        self.scalar_results = list(scalar_results)
        self.executed = []
        self.scalar_statements = []
        self.added = []
        self.commits = 0
        self.refreshed = []

    def execute(self, statement, parameters=None):
        self.executed.append((statement, parameters))

    def get(self, model, object_id, *, with_for_update=False):
        assert model is EmbeddingConfigurationState
        assert object_id == 1
        assert with_for_update is True
        return self.state

    def scalar(self, statement):
        self.scalar_statements.append(statement)
        return self.scalar_results.pop(0)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def refresh(self, value):
        self.refreshed.append(value)


def test_current_embedding_configuration_needs_no_new_job(monkeypatch) -> None:
    state = SimpleNamespace(fingerprint="current")
    db = ReconciliationSession(state)
    monkeypatch.setattr(
        embedding_configuration_service.settings_service,
        "embedding_configuration_fingerprint",
        lambda: "current",
    )

    job = embedding_configuration_service.reconcile_embedding_configuration(
        db,
        uuid4(),
    )

    assert job is None
    assert db.commits == 1
    assert db.added == []
    assert db.scalar_results == []
    assert db.executed[0][1] == {
        "lock_id": embedding_configuration_service.EMBEDDING_CONFIGURATION_LOCK_ID
    }


def test_changed_configuration_adds_state_and_job_in_one_commit(monkeypatch) -> None:
    state = SimpleNamespace(fingerprint="old")
    db = ReconciliationSession(state, scalar_results=[uuid4(), None])
    owner_user_id = uuid4()
    job = SimpleNamespace(id=uuid4())
    added_jobs = []
    monkeypatch.setattr(
        embedding_configuration_service.settings_service,
        "embedding_configuration_fingerprint",
        lambda: "current",
    )
    monkeypatch.setattr(
        embedding_configuration_service.job_service,
        "add_job",
        lambda *args, **kwargs: added_jobs.append((args, kwargs)) or job,
    )

    result = embedding_configuration_service.reconcile_embedding_configuration(
        db,
        owner_user_id,
    )

    assert result is job
    assert state.fingerprint == "current"
    assert db.added == [state]
    assert db.commits == 1
    assert db.refreshed == [job]
    assert added_jobs == [
        (
            (db, owner_user_id, None, JobType.REBUILD_ALL_EMBEDDINGS),
            {"configuration_fingerprint": "current"},
        )
    ]


def test_initial_consistent_index_only_initializes_state(monkeypatch) -> None:
    db = ReconciliationSession(None, scalar_results=[None, None, None])
    monkeypatch.setattr(
        embedding_configuration_service.settings_service,
        "embedding_configuration_fingerprint",
        lambda: "current",
    )
    monkeypatch.setattr(
        embedding_configuration_service.settings_service,
        "embedding_index_id",
        lambda: "index-current",
    )

    result = embedding_configuration_service.reconcile_embedding_configuration(
        db,
        uuid4(),
    )

    assert result is None
    assert len(db.added) == 1
    state = db.added[0]
    assert isinstance(state, EmbeddingConfigurationState)
    assert state.id == 1
    assert state.fingerprint == "current"
    assert db.commits == 1


def test_existing_active_job_for_current_fingerprint_is_not_duplicated(
    monkeypatch,
) -> None:
    db = ReconciliationSession(None, scalar_results=[uuid4(), uuid4()])
    add_job_calls = []
    monkeypatch.setattr(
        embedding_configuration_service.settings_service,
        "embedding_configuration_fingerprint",
        lambda: "current",
    )
    monkeypatch.setattr(
        embedding_configuration_service.settings_service,
        "embedding_index_id",
        lambda: "index-current",
    )
    monkeypatch.setattr(
        embedding_configuration_service.job_service,
        "add_job",
        lambda *args, **kwargs: add_job_calls.append((args, kwargs)),
    )

    result = embedding_configuration_service.reconcile_embedding_configuration(
        db,
        uuid4(),
    )

    assert result is None
    assert add_job_calls == []
    assert db.commits == 1
    existing_job_statement = db.scalar_statements[-1]
    parameter_values = existing_job_statement.compile().params.values()
    status_values = next(
        value
        for value in parameter_values
        if isinstance(value, list)
    )
    assert set(status_values) == (
        embedding_configuration_service.REUSABLE_CONFIGURATION_JOB_STATUSES
    )
    assert "success" not in status_values
    assert "failed" not in status_values
    assert "cancelled" not in status_values
    assert "cancel_requested" not in status_values


def test_configuration_cycle_creates_new_job_when_no_active_match(monkeypatch) -> None:
    state = SimpleNamespace(fingerprint="fingerprint-b")
    db = ReconciliationSession(state, scalar_results=[uuid4(), None])
    job = SimpleNamespace(id=uuid4())
    added_jobs = []
    monkeypatch.setattr(
        embedding_configuration_service.settings_service,
        "embedding_configuration_fingerprint",
        lambda: "fingerprint-a",
    )
    monkeypatch.setattr(
        embedding_configuration_service.job_service,
        "add_job",
        lambda *args, **kwargs: added_jobs.append((args, kwargs)) or job,
    )

    result = embedding_configuration_service.reconcile_embedding_configuration(
        db,
        uuid4(),
    )

    assert result is job
    assert state.fingerprint == "fingerprint-a"
    assert len(added_jobs) == 1
    assert added_jobs[0][1] == {
        "configuration_fingerprint": "fingerprint-a"
    }
