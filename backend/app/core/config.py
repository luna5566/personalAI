from functools import lru_cache
from pathlib import Path
from uuid import UUID

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DATABASE_VECTOR_DIMENSIONS = 1536
DATABASE_HNSW_M = 16
DATABASE_HNSW_EF_CONSTRUCTION = 64
MULTIPART_BODY_OVERHEAD_BYTES = 64 * 1024
AI_PROVIDER_RESPONSE_MIN_BYTES = 64 * 1024
AI_PROVIDER_RESPONSE_MAX_BYTES = 64 * 1024 * 1024
AUTH_SECRET_MIN_BYTES = 32
ACCESS_TOKEN_MAX_EXPIRE_MINUTES = 30 * 24 * 60
LOCAL_AUTH_ENVIRONMENTS = frozenset({"local", "test"})
INSECURE_AUTH_SECRET_KEYS = frozenset(
    {
        "change-me-in-production",
        "change-me-in-production-use-at-least-32-bytes",
    }
)


class Settings(BaseSettings):
    app_name: str = "Personal AI Knowledge Assistant"
    app_env: str = "local"
    api_prefix: str = "/api"
    cors_origins: list[str] = [
        "http://127.0.0.1:5600",
        "http://localhost:5600",
    ]

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/personal_ai"
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_pool_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=10, ge=0.1, le=300)
    database_statement_timeout_seconds: float = Field(default=30, ge=0.1, le=3600)
    database_health_statement_timeout_seconds: float = Field(default=2, ge=0.1, le=30)
    database_retry_after_seconds: int = Field(default=5, ge=1, le=300)

    default_user_id: UUID = Field(default=UUID("00000000-0000-0000-0000-000000000001"))
    runtime_settings_admin_user_id: UUID = Field(default=UUID("00000000-0000-0000-0000-000000000001"))
    auth_secret_key: str = Field(default="change-me-in-production", min_length=1)
    auth_token_issuer: str = Field(default="personal-ai-backend", min_length=1, max_length=255)
    auth_token_audience: str = Field(default="personal-ai-client", min_length=1, max_length=255)
    auth_token_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    auth_max_active_sessions_per_user: int = Field(default=10, ge=1, le=100)
    auth_registration_enabled: bool | None = None
    auth_registration_invite_required: bool | None = None
    access_token_expire_minutes: int = Field(
        default=10080,
        ge=1,
        le=ACCESS_TOKEN_MAX_EXPIRE_MINUTES,
    )
    auth_login_account_max_failures: int = Field(default=5, ge=1, le=100)
    auth_login_client_max_failures: int = Field(default=20, ge=1, le=1000)
    auth_login_window_seconds: int = Field(default=900, ge=60, le=86400)
    auth_login_lockout_seconds: int = Field(default=900, ge=60, le=86400)
    auth_login_attempt_retention_seconds: int = Field(
        default=86400,
        ge=60,
        le=7 * 86400,
    )
    auth_registration_client_max_attempts: int = Field(default=5, ge=1, le=100)
    auth_registration_window_seconds: int = Field(default=3600, ge=60, le=86400)
    auth_registration_lockout_seconds: int = Field(default=3600, ge=60, le=86400)
    auth_registration_attempt_retention_seconds: int = Field(
        default=86400,
        ge=60,
        le=7 * 86400,
    )

    llm_provider: str = "openai_compatible"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    ai_provider_max_response_size_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=AI_PROVIDER_RESPONSE_MIN_BYTES,
        le=AI_PROVIDER_RESPONSE_MAX_BYTES,
    )
    ai_provider_max_concurrent_requests: int = Field(
        default=8,
        ge=1,
        le=100,
    )
    # Per-user shared quota for chat query and organize endpoints.
    # The first N requests in the window are allowed; request N + 1 is blocked.
    ai_user_max_requests: int = Field(default=30, ge=1, le=1000)
    ai_user_window_seconds: int = Field(default=60, ge=10, le=3600)
    ai_user_lockout_seconds: int = Field(default=60, ge=10, le=3600)
    ai_user_attempt_retention_seconds: int = Field(
        default=86400,
        ge=60,
        le=7 * 86400,
    )

    embedding_provider: str = "openai_compatible"
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=DATABASE_VECTOR_DIMENSIONS, ge=DATABASE_VECTOR_DIMENSIONS, le=DATABASE_VECTOR_DIMENSIONS)
    hnsw_ef_search: int = Field(default=100, ge=1, le=1000)
    hnsw_max_scan_tuples: int = Field(default=20000, ge=1, le=1_000_000)

    storage_root: Path = Path("storage_data")
    storage_backend: str = "local"
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_use_ssl: bool = True
    s3_key_prefix: str = "documents"
    max_upload_size_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    max_request_body_size_bytes: int = Field(default=30 * 1024 * 1024, ge=1024)
    storage_audit_batch_size: int = Field(default=500, ge=1, le=10000)
    storage_audit_sample_limit: int = Field(default=100, ge=0, le=10000)
    storage_deletion_interval_seconds: int = Field(default=60, ge=1, le=3600)
    storage_deletion_batch_size: int = Field(default=50, ge=1, le=1000)
    storage_deletion_lease_seconds: int = Field(default=300, ge=1, le=3600)
    storage_deletion_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    storage_deletion_retry_max_seconds: int = Field(default=3600, ge=1, le=86400)
    storage_deletion_statement_timeout_seconds: float = Field(
        default=30,
        ge=0.1,
        le=3600,
    )
    storage_deletion_shutdown_timeout_seconds: float = Field(
        default=30,
        ge=0,
        le=3600,
    )
    stale_job_after_minutes: int = Field(default=15, ge=1)
    job_heartbeat_interval_seconds: int = Field(default=30, ge=1)
    job_recovery_interval_seconds: int = Field(default=60, ge=1)
    job_recovery_batch_size: int = Field(default=50, ge=1, le=1000)
    job_recovery_max_active_workers: int = Field(default=50, ge=1, le=1000)
    job_recovery_scan_stale_after_seconds: int = Field(default=30, ge=1, le=3600)
    job_recovery_statement_timeout_seconds: float = Field(default=30, ge=0.1, le=3600)
    job_recovery_shutdown_timeout_seconds: float = Field(default=30, ge=0, le=3600)
    job_retention_days: int = Field(default=30, ge=1)
    maintenance_cleanup_batch_size: int = Field(default=1000, ge=1, le=10000)

    ocr_provider: str = "disabled"
    ocr_base_url: str | None = None
    ocr_api_key: str | None = None
    ocr_model: str = "gpt-4o-mini"
    speech_to_text_provider: str = "disabled"
    speech_to_text_base_url: str | None = None
    speech_to_text_api_key: str | None = None
    speech_to_text_model: str = "whisper-1"

    rerank_provider: str = "disabled"
    rerank_base_url: str | None = None
    rerank_api_key: str | None = None
    rerank_model: str = "rerank-v3.5"

    metrics_enabled: bool = True
    log_format: str = "text"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def registration_enabled(self) -> bool:
        if self.auth_registration_enabled is not None:
            return self.auth_registration_enabled
        return self.app_env.strip().casefold() in LOCAL_AUTH_ENVIRONMENTS

    @property
    def registration_invite_required(self) -> bool:
        if self.auth_registration_invite_required is not None:
            return self.auth_registration_invite_required
        return self.app_env.strip().casefold() not in LOCAL_AUTH_ENVIRONMENTS

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "Settings":
        normalized_secret = self.auth_secret_key.strip().casefold()
        if not normalized_secret:
            raise ValueError("AUTH_SECRET_KEY must not be blank")
        if not self.auth_token_issuer.strip():
            raise ValueError("AUTH_TOKEN_ISSUER must not be blank")
        if not self.auth_token_audience.strip():
            raise ValueError("AUTH_TOKEN_AUDIENCE must not be blank")

        required_retention = max(
            self.auth_login_window_seconds,
            self.auth_login_lockout_seconds,
        )
        if self.auth_login_attempt_retention_seconds < required_retention:
            raise ValueError(
                "AUTH_LOGIN_ATTEMPT_RETENTION_SECONDS must be at least the login "
                "window and lockout duration"
            )

        required_registration_retention = max(
            self.auth_registration_window_seconds,
            self.auth_registration_lockout_seconds,
        )
        if (
            self.auth_registration_attempt_retention_seconds
            < required_registration_retention
        ):
            raise ValueError(
                "AUTH_REGISTRATION_ATTEMPT_RETENTION_SECONDS must be at least "
                "the registration window and lockout duration"
            )

        required_ai_retention = max(
            self.ai_user_window_seconds,
            self.ai_user_lockout_seconds,
        )
        if self.ai_user_attempt_retention_seconds < required_ai_retention:
            raise ValueError(
                "AI_USER_ATTEMPT_RETENTION_SECONDS must be at least "
                "the AI request window and lockout duration"
            )

        if (
            self.storage_deletion_retry_max_seconds
            < self.storage_deletion_retry_base_seconds
        ):
            raise ValueError(
                "STORAGE_DELETION_RETRY_MAX_SECONDS must be at least "
                "STORAGE_DELETION_RETRY_BASE_SECONDS"
            )

        minimum_request_limit = (
            self.max_upload_size_bytes + MULTIPART_BODY_OVERHEAD_BYTES
        )
        if self.max_request_body_size_bytes < minimum_request_limit:
            raise ValueError(
                "MAX_REQUEST_BODY_SIZE_BYTES must be at least "
                "MAX_UPLOAD_SIZE_BYTES plus 65536 bytes"
            )

        environment = self.app_env.strip().casefold()
        if environment in LOCAL_AUTH_ENVIRONMENTS:
            return self

        if (
            normalized_secret in INSECURE_AUTH_SECRET_KEYS
            or len(self.auth_secret_key.encode("utf-8")) < AUTH_SECRET_MIN_BYTES
        ):
            raise ValueError(
                "AUTH_SECRET_KEY must be a non-placeholder secret of at least "
                f"{AUTH_SECRET_MIN_BYTES} UTF-8 bytes outside local/test"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
