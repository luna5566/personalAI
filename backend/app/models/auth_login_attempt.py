from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuthLoginAttempt(Base):
    __tablename__ = "auth_login_attempts"
    __table_args__ = (
        CheckConstraint(
            "failed_attempts >= 0",
            name="ck_auth_login_attempts_failed_attempts_nonnegative",
        ),
        Index("ix_auth_login_attempts_updated_at", "updated_at"),
    )

    scope_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
