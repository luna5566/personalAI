"""index stable list pagination

Revision ID: 0024_stable_pagination
Revises: 0023_job_query_indexes
Create Date: 2026-07-18
"""

from typing import Union

from alembic import op


revision: str = "0024_stable_pagination"
down_revision: Union[str, None] = "0023_job_query_indexes"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        _create_index(
            "ix_documents_user_created_id",
            "documents",
            ["user_id", "created_at", "id"],
        )
        _create_index(
            "ix_conversations_user_updated_id",
            "conversations",
            ["user_id", "updated_at", "id"],
        )
        _create_index(
            "ix_messages_conversation_created_id",
            "messages",
            ["conversation_id", "user_id", "created_at", "id"],
        )
        _create_index(
            "ix_auth_registration_invites_created_id",
            "auth_registration_invites",
            ["created_at", "id"],
        )
        _drop_index("ix_documents_user_id", "documents")
        _drop_index("ix_conversations_user_id", "conversations")
        _drop_index("ix_conversations_user_updated", "conversations")
        _drop_index("ix_messages_conversation_id", "messages")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        _create_index("ix_documents_user_id", "documents", ["user_id"])
        _create_index("ix_conversations_user_id", "conversations", ["user_id"])
        _create_index(
            "ix_conversations_user_updated",
            "conversations",
            ["user_id", "updated_at"],
        )
        _create_index(
            "ix_messages_conversation_id",
            "messages",
            ["conversation_id"],
        )
        _drop_index("ix_auth_registration_invites_created_id", "auth_registration_invites")
        _drop_index("ix_messages_conversation_created_id", "messages")
        _drop_index("ix_conversations_user_updated_id", "conversations")
        _drop_index("ix_documents_user_created_id", "documents")


def _create_index(name: str, table: str, columns: list[str]) -> None:
    op.create_index(
        name,
        table,
        columns,
        unique=False,
        postgresql_concurrently=True,
        if_not_exists=True,
    )


def _drop_index(name: str, table: str) -> None:
    op.drop_index(
        name,
        table_name=table,
        postgresql_concurrently=True,
        if_exists=True,
    )
