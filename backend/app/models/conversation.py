from datetime import datetime
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, query_expression, relationship

from app.core.database import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_user_updated_id",
            "user_id",
            "updated_at",
            "id",
        ),
        Index(
            "ix_conversations_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    scope_preview: Mapped[dict | None] = query_expression()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
