from datetime import datetime
from enum import Enum
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobType(str, Enum):
    INDEX_DOCUMENT = "index_document"
    REBUILD_EMBEDDINGS = "rebuild_embeddings"
    REBUILD_ALL_EMBEDDINGS = "rebuild_all_embeddings"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    SUCCESS = "success"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_user_status", "user_id", "status"),
        Index("ix_jobs_updated_at_id", "updated_at", "id"),
        Index(
            "ix_jobs_recoverable_created_at_id",
            "created_at",
            "id",
            postgresql_where=text(
                "status IN ('pending', 'cancel_requested', 'running')"
            ),
        ),
        Index(
            "ix_jobs_user_updated_created_id",
            "user_id",
            "updated_at",
            "created_at",
            "id",
        ),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    document_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
    )
    retry_of_job_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        index=True,
    )
    run_token: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_fingerprint: Mapped[str | None] = mapped_column(
        String(192),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.PENDING.value)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
