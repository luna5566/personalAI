import pytest
from pydantic import ValidationError

from app.core.config import (
    AI_PROVIDER_RESPONSE_MAX_BYTES,
    AI_PROVIDER_RESPONSE_MIN_BYTES,
    MULTIPART_BODY_OVERHEAD_BYTES,
    Settings,
)


@pytest.mark.parametrize("app_env", ["local", "LOCAL", " test "])
def test_local_and_test_environments_allow_development_secret(app_env: str) -> None:
    configured = Settings(
        _env_file=None,
        app_env=app_env,
        auth_secret_key="local-only",
    )

    assert configured.auth_secret_key == "local-only"


@pytest.mark.parametrize(
    "auth_secret_key",
    [
        "change-me-in-production",
        "change-me-in-production-use-at-least-32-bytes",
        "x" * 31,
    ],
)
def test_non_local_environment_rejects_insecure_secret(
    auth_secret_key: str,
) -> None:
    with pytest.raises(ValidationError, match="AUTH_SECRET_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            auth_secret_key=auth_secret_key,
        )


def test_non_local_environment_accepts_32_byte_secret() -> None:
    configured = Settings(
        _env_file=None,
        app_env="staging",
        auth_secret_key="x" * 32,
    )

    assert configured.auth_secret_key == "x" * 32


@pytest.mark.parametrize(
    ("app_env", "expected"),
    [("local", True), (" test ", True), ("staging", False), ("production", False)],
)
def test_registration_default_depends_on_environment(
    app_env: str,
    expected: bool,
) -> None:
    configured = Settings(
        _env_file=None,
        app_env=app_env,
        auth_secret_key="x" * 32,
    )

    assert configured.registration_enabled is expected
    assert configured.registration_invite_required is (not expected)


@pytest.mark.parametrize("enabled", [True, False])
def test_explicit_registration_policy_overrides_environment(enabled: bool) -> None:
    configured = Settings(
        _env_file=None,
        app_env="production",
        auth_secret_key="x" * 32,
        auth_registration_enabled=enabled,
    )

    assert configured.registration_enabled is enabled


@pytest.mark.parametrize("required", [True, False])
def test_explicit_invite_policy_overrides_environment(required: bool) -> None:
    configured = Settings(
        _env_file=None,
        app_env="production",
        auth_secret_key="x" * 32,
        auth_registration_invite_required=required,
    )

    assert configured.registration_invite_required is required


@pytest.mark.parametrize("expire_minutes", [0, 30 * 24 * 60 + 1])
def test_access_token_expiration_must_stay_within_bounds(
    expire_minutes: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            access_token_expire_minutes=expire_minutes,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("auth_token_clock_skew_seconds", -1),
        ("auth_token_clock_skew_seconds", 301),
        ("auth_max_active_sessions_per_user", 0),
        ("auth_max_active_sessions_per_user", 101),
    ],
)
def test_auth_session_settings_stay_within_bounds(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize("field", ["auth_token_issuer", "auth_token_audience"])
def test_token_identity_settings_must_not_be_blank(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: "   "})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("auth_login_account_max_failures", 0),
        ("auth_login_client_max_failures", 0),
        ("auth_login_window_seconds", 59),
        ("auth_login_lockout_seconds", 86401),
        ("auth_login_attempt_retention_seconds", 7 * 86400 + 1),
    ],
)
def test_login_rate_limit_settings_stay_within_bounds(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_login_attempt_retention_covers_window_and_lockout() -> None:
    with pytest.raises(
        ValidationError,
        match="AUTH_LOGIN_ATTEMPT_RETENTION_SECONDS",
    ):
        Settings(
            _env_file=None,
            auth_login_window_seconds=600,
            auth_login_lockout_seconds=1200,
            auth_login_attempt_retention_seconds=900,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("auth_registration_client_max_attempts", 0),
        ("auth_registration_window_seconds", 59),
        ("auth_registration_lockout_seconds", 86401),
        ("auth_registration_attempt_retention_seconds", 7 * 86400 + 1),
    ],
)
def test_registration_rate_limit_settings_stay_within_bounds(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_registration_attempt_retention_covers_window_and_lockout() -> None:
    with pytest.raises(
        ValidationError,
        match="AUTH_REGISTRATION_ATTEMPT_RETENTION_SECONDS",
    ):
        Settings(
            _env_file=None,
            auth_registration_window_seconds=600,
            auth_registration_lockout_seconds=1200,
            auth_registration_attempt_retention_seconds=900,
        )


@pytest.mark.parametrize("batch_size", [0, 10001])
def test_maintenance_cleanup_batch_size_stays_within_bounds(
    batch_size: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            maintenance_cleanup_batch_size=batch_size,
        )


@pytest.mark.parametrize(
    "response_limit",
    [
        AI_PROVIDER_RESPONSE_MIN_BYTES - 1,
        AI_PROVIDER_RESPONSE_MAX_BYTES + 1,
    ],
)
def test_ai_provider_response_limit_stays_within_bounds(
    response_limit: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ai_provider_max_response_size_bytes=response_limit,
        )


@pytest.mark.parametrize("concurrency_limit", [0, 101])
def test_ai_provider_concurrency_limit_stays_within_bounds(
    concurrency_limit: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ai_provider_max_concurrent_requests=concurrency_limit,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("storage_audit_batch_size", 0),
        ("storage_audit_batch_size", 10001),
        ("storage_audit_sample_limit", -1),
        ("storage_audit_sample_limit", 10001),
    ],
)
def test_storage_audit_settings_stay_within_bounds(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_request_body_limit_must_cover_upload_and_multipart_metadata() -> None:
    upload_limit = 10 * 1024 * 1024

    with pytest.raises(ValidationError, match="MAX_REQUEST_BODY_SIZE_BYTES"):
        Settings(
            _env_file=None,
            max_upload_size_bytes=upload_limit,
            max_request_body_size_bytes=(
                upload_limit + MULTIPART_BODY_OVERHEAD_BYTES - 1
            ),
        )

    configured = Settings(
        _env_file=None,
        max_upload_size_bytes=upload_limit,
        max_request_body_size_bytes=(
            upload_limit + MULTIPART_BODY_OVERHEAD_BYTES
        ),
    )
    assert configured.max_request_body_size_bytes == (
        upload_limit + MULTIPART_BODY_OVERHEAD_BYTES
    )
