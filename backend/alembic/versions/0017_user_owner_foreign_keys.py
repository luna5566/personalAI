"""add user ownership foreign keys

Revision ID: 0017_user_owner_fks
Revises: 0016_invite_revocation
Create Date: 2026-07-18
"""

from typing import Union

from alembic import op


revision: str = "0017_user_owner_fks"
down_revision: Union[str, None] = "0016_invite_revocation"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


USER_OWNER_FOREIGN_KEYS = (
    ("documents", "fk_documents_user_id_users"),
    ("document_chunks", "fk_document_chunks_user_id_users"),
    ("chunk_embeddings", "fk_chunk_embeddings_user_id_users"),
    ("conversations", "fk_conversations_user_id_users"),
    ("messages", "fk_messages_user_id_users"),
    ("jobs", "fk_jobs_user_id_users"),
    ("tags", "fk_tags_user_id_users"),
)


def upgrade() -> None:
    for table_name, constraint_name in USER_OWNER_FOREIGN_KEYS:
        op.create_foreign_key(
            constraint_name,
            table_name,
            "users",
            ["user_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    for table_name, constraint_name in reversed(USER_OWNER_FOREIGN_KEYS):
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
