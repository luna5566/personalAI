import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import BackgroundTasks, FastAPI, Response
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.deps import authenticated_user_id, db_session
from app.api.routes import jobs as jobs_routes
from app.api.routes import settings as settings_routes
from app.core.config import DATABASE_VECTOR_DIMENSIONS, settings
from app.core.exceptions import register_exception_handlers
from app.models.job import JobStatus, JobType
from app.schemas.settings import RuntimeSettingsUpdate
from app.services import settings_service


def test_env_updates_replace_atomically_and_preserve_other_values(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / ".env"
    original = "# local config\nKEEP=value\nLLM_PROVIDER=old\n"
    path.write_text(original, encoding="utf-8")
    real_fsync = os.fsync
    real_replace = os.replace
    events = []

    def tracked_fsync(file_descriptor):
        events.append("fsync")
        real_fsync(file_descriptor)

    def tracked_replace(source, target):
        events.append("replace")
        assert path.read_text(encoding="utf-8") == original
        assert target == path
        assert Path(source).parent == path.parent
        assert Path(source).name.startswith(".env.")
        real_replace(source, target)

    monkeypatch.setattr(settings_service.os, "fsync", tracked_fsync)
    monkeypatch.setattr(settings_service.os, "replace", tracked_replace)

    settings_service._write_env_updates(
        path,
        {
            "LLM_PROVIDER": "local_extractive",
            "LLM_API_KEY": "key with spaces",
        },
    )

    assert events == ["fsync", "replace"]
    assert path.read_text(encoding="utf-8") == (
        "# local config\n"
        "KEEP=value\n"
        "LLM_PROVIDER=local_extractive\n"
        'LLM_API_KEY="key with spaces"\n'
    )
    assert list(tmp_path.glob(".env.*.tmp")) == []


def test_env_replace_failure_preserves_original_and_removes_temporary_file(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / ".env"
    original = "KEEP=original\n"
    path.write_text(original, encoding="utf-8")

    def fail_replace(source, target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(settings_service.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failure"):
        settings_service._write_env_updates(path, {"KEEP": "changed"})

    assert path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".env.*.tmp")) == []


def test_runtime_settings_update_does_not_apply_memory_after_write_failure(
    monkeypatch,
) -> None:
    applied = []
    monkeypatch.setattr(
        settings_service,
        "_write_env_updates",
        lambda *args: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    monkeypatch.setattr(
        settings_service,
        "_apply_runtime_updates",
        lambda updates: applied.append(updates),
    )

    with pytest.raises(OSError, match="disk unavailable"):
        settings_service.update_runtime_settings(_runtime_update_payload())

    assert applied == []


def test_runtime_settings_updates_are_serialized(monkeypatch) -> None:
    state_lock = threading.Lock()
    start_barrier = threading.Barrier(4)
    active_writers = 0
    max_active_writers = 0

    def tracked_write(path, updates):
        nonlocal active_writers, max_active_writers
        with state_lock:
            active_writers += 1
            max_active_writers = max(max_active_writers, active_writers)
        time.sleep(0.02)
        with state_lock:
            active_writers -= 1

    def update_once():
        start_barrier.wait()
        return settings_service.update_runtime_settings(_runtime_update_payload())

    monkeypatch.setattr(settings_service, "_write_env_updates", tracked_write)
    monkeypatch.setattr(settings_service, "_apply_runtime_updates", lambda updates: None)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: update_once(), range(4)))

    assert len(results) == 4
    assert max_active_writers == 1


def test_runtime_settings_are_admin_only() -> None:
    with pytest.raises(PermissionError, match="管理员"):
        settings_service.ensure_runtime_settings_access(uuid4())


def test_runtime_settings_cannot_be_changed_in_production() -> None:
    previous_app_env = settings.app_env
    settings.app_env = "production"
    try:
        with pytest.raises(PermissionError, match="不允许在线修改"):
            settings_service.ensure_runtime_settings_access(
                settings.runtime_settings_admin_user_id,
                write=True,
            )
    finally:
        settings.app_env = previous_app_env


def test_embedding_dimensions_must_match_database_vector() -> None:
    assert settings.embedding_dimensions == DATABASE_VECTOR_DIMENSIONS

    with pytest.raises(ValueError, match="固定"):
        settings_service.update_runtime_settings(
            RuntimeSettingsUpdate(
                llm_provider="local_extractive",
                embedding_provider="local_hash",
                embedding_model="local_hash",
                embedding_dimensions=DATABASE_VECTOR_DIMENSIONS + 1,
            )
        )


def test_default_runtime_settings_admin_is_local_user() -> None:
    assert settings.runtime_settings_admin_user_id == UUID(
        "00000000-0000-0000-0000-000000000001"
    )


def test_openai_compatible_provider_requires_api_key() -> None:
    previous_key = settings.llm_api_key
    settings.llm_api_key = None
    try:
        with pytest.raises(ValueError, match=r"LLM.*API Key"):
            settings_service.update_runtime_settings(
                RuntimeSettingsUpdate(
                    llm_provider="openai_compatible",
                    llm_model="gpt-4o-mini",
                    embedding_provider="local_hash",
                    embedding_model="local_hash",
                    embedding_dimensions=DATABASE_VECTOR_DIMENSIONS,
                )
            )
    finally:
        settings.llm_api_key = previous_key


def test_cannot_clear_key_for_enabled_openai_provider() -> None:
    previous_provider = settings.ocr_provider
    previous_key = settings.ocr_api_key
    settings.ocr_provider = "openai_compatible"
    settings.ocr_api_key = "configured"
    try:
        with pytest.raises(ValueError, match=r"OCR.*API Key"):
            settings_service.update_runtime_settings(
                RuntimeSettingsUpdate(
                    llm_provider="local_extractive",
                    embedding_provider="local_hash",
                    embedding_model="local_hash",
                    embedding_dimensions=DATABASE_VECTOR_DIMENSIONS,
                    ocr_provider="openai_compatible",
                    ocr_model="gpt-4o-mini",
                    clear_ocr_api_key=True,
                )
            )
    finally:
        settings.ocr_provider = previous_provider
        settings.ocr_api_key = previous_key


def test_local_hash_fingerprint_ignores_unused_model_and_credentials(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "local_hash")
    monkeypatch.setattr(settings, "embedding_model", "unused-model-a")
    monkeypatch.setattr(settings, "embedding_api_key", "unused-key-a")
    first = settings_service.embedding_configuration_fingerprint()
    assert "unused-key-a" not in first

    monkeypatch.setattr(settings, "embedding_model", "unused-model-b")
    monkeypatch.setattr(settings, "embedding_api_key", "unused-key-b")

    assert settings_service.embedding_configuration_fingerprint() == first


def test_openai_fingerprint_changes_with_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "openai_compatible")
    monkeypatch.setattr(settings, "embedding_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "embedding_model", "embedding-small")
    monkeypatch.setattr(settings, "embedding_api_key", "key-a")
    first = settings_service.embedding_configuration_fingerprint()
    assert "key-a" not in first

    monkeypatch.setattr(settings, "embedding_api_key", "key-b")

    assert settings_service.embedding_configuration_fingerprint() != first


def test_embedding_change_creates_global_rebuild_job(monkeypatch) -> None:
    job = SimpleNamespace(id=uuid4())
    reconciled = []
    background_tasks = BackgroundTasks()
    response = Response()
    db = MagicMock()
    updated = settings_service.runtime_settings_read()

    monkeypatch.setattr(
        settings_routes.settings_service,
        "ensure_runtime_settings_access",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        settings_routes.settings_service,
        "update_runtime_settings",
        lambda payload: updated,
    )
    monkeypatch.setattr(
        settings_routes.embedding_configuration_service,
        "reconcile_embedding_configuration",
        lambda db, user_id: reconciled.append((db, user_id)) or job,
    )

    result = settings_routes.update_runtime_settings(
        _runtime_update_payload(),
        background_tasks,
        response,
        db,
        settings.runtime_settings_admin_user_id,
    )

    assert result is updated
    assert reconciled == [(db, settings.runtime_settings_admin_user_id)]
    assert response.headers[settings_routes.EMBEDDING_REBUILD_JOB_HEADER] == str(
        job.id
    )
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is settings_routes.run_job_with_worker_limit
    assert task.args == (
        settings_routes.rebuild_embeddings,
        job.id,
        None,
    )


def test_non_embedding_change_does_not_create_rebuild_job(monkeypatch) -> None:
    background_tasks = BackgroundTasks()
    response = Response()
    reconciled = []
    db = MagicMock()

    monkeypatch.setattr(
        settings_routes.settings_service,
        "ensure_runtime_settings_access",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        settings_routes.settings_service,
        "update_runtime_settings",
        lambda payload: settings_service.runtime_settings_read(),
    )
    monkeypatch.setattr(
        settings_routes.embedding_configuration_service,
        "reconcile_embedding_configuration",
        lambda db, user_id: reconciled.append((db, user_id)) or None,
    )

    settings_routes.update_runtime_settings(
        _runtime_update_payload(),
        background_tasks,
        response,
        db,
        settings.runtime_settings_admin_user_id,
    )

    assert reconciled == [(db, settings.runtime_settings_admin_user_id)]
    assert settings_routes.EMBEDDING_REBUILD_JOB_HEADER not in response.headers
    assert background_tasks.tasks == []


@pytest.mark.parametrize(
    "internal_error",
    [
        PermissionError("C:\\private\\personalAI\\backend\\.env"),
        ValueError("https://internal.example api_key=secret"),
    ],
)
def test_runtime_settings_route_hides_unexpected_errors(
    monkeypatch,
    internal_error,
) -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(settings_routes.router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_user_id] = (
        lambda: settings.runtime_settings_admin_user_id
    )
    monkeypatch.setattr(
        settings_routes.settings_service,
        "ensure_runtime_settings_access",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        settings_routes.settings_service,
        "embedding_configuration_fingerprint",
        lambda: "unchanged",
    )
    monkeypatch.setattr(
        settings_routes.settings_service,
        "update_runtime_settings",
        lambda payload: (_ for _ in ()).throw(internal_error),
    )

    response = TestClient(app, raise_server_exceptions=False).patch(
        "/settings/runtime",
        json=_runtime_update_payload().model_dump(),
    )

    assert response.status_code == 500
    assert response.json() == {
        "message": "服务器内部错误",
        "detail": "服务器内部错误",
    }
    assert "private" not in response.text
    assert "internal.example" not in response.text
    assert "api_key" not in response.text


def test_runtime_settings_database_failure_is_recoverable_and_not_dispatched(
    monkeypatch,
) -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(settings_routes.router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_user_id] = (
        lambda: settings.runtime_settings_admin_user_id
    )
    dispatched = []
    monkeypatch.setattr(
        settings_routes.settings_service,
        "ensure_runtime_settings_access",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        settings_routes.settings_service,
        "update_runtime_settings",
        lambda payload: settings_service.runtime_settings_read(),
    )
    monkeypatch.setattr(
        settings_routes.embedding_configuration_service,
        "reconcile_embedding_configuration",
        lambda *args: (_ for _ in ()).throw(
            OperationalError(
                "INSERT INTO jobs",
                {},
                RuntimeError("database host api_key=secret"),
            )
        ),
    )
    monkeypatch.setattr(
        settings_routes,
        "rebuild_embeddings",
        lambda *args: dispatched.append(args),
    )

    response = TestClient(app, raise_server_exceptions=False).patch(
        "/settings/runtime",
        json=_runtime_update_payload().model_dump(),
    )

    assert response.status_code == 503
    assert response.json() == {
        "message": "数据库暂时不可用，请稍后重试",
        "detail": "数据库暂时不可用，请稍后重试",
    }
    assert "api_key" not in response.text
    assert dispatched == []


def test_manual_global_rebuild_is_admin_only_and_covers_all_users(monkeypatch) -> None:
    now = datetime.now(UTC)
    job = SimpleNamespace(
        id=uuid4(),
        user_id=settings.runtime_settings_admin_user_id,
        document_id=None,
        retry_of_job_id=None,
        job_type=JobType.REBUILD_ALL_EMBEDDINGS.value,
        status=JobStatus.PENDING.value,
        progress=0,
        message="等待处理",
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    created = []
    access_checks = []
    background_tasks = BackgroundTasks()

    monkeypatch.setattr(
        jobs_routes.settings_service,
        "ensure_runtime_settings_access",
        lambda user_id: access_checks.append(user_id),
    )
    monkeypatch.setattr(
        jobs_routes.embedding_configuration_service,
        "reconcile_embedding_configuration",
        lambda db, user_id: None,
    )
    monkeypatch.setattr(
        jobs_routes.job_service,
        "create_job",
        lambda db, user_id, document_id, job_type, **kwargs: created.append(
            (user_id, document_id, job_type, kwargs)
        )
        or job,
    )

    result = jobs_routes.start_rebuild_all_embeddings(
        background_tasks,
        MagicMock(),
        settings.runtime_settings_admin_user_id,
    )

    assert result.id == job.id
    assert access_checks == [settings.runtime_settings_admin_user_id]
    assert created == [
        (
            settings.runtime_settings_admin_user_id,
            None,
            JobType.REBUILD_ALL_EMBEDDINGS,
            {
                "configuration_fingerprint": (
                    settings_service.embedding_configuration_fingerprint()
                )
            },
        )
    ]
    task = background_tasks.tasks[0]
    assert task.func is jobs_routes.run_job_with_worker_limit
    assert task.args == (
        jobs_routes.rebuild_embeddings,
        job.id,
        None,
    )


def _runtime_update_payload() -> RuntimeSettingsUpdate:
    return RuntimeSettingsUpdate(
        llm_provider="local_extractive",
        embedding_provider="local_hash",
        embedding_model="local_hash",
        embedding_dimensions=DATABASE_VECTOR_DIMENSIONS,
    )
