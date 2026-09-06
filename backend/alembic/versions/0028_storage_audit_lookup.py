"""Add bounded storage audit lookup index.

Revision ID: 0028_storage_audit_lookup
Revises: 0027_online_hnsw_options
"""

from alembic import op


revision = "0028_storage_audit_lookup"
down_revision = "0027_online_hnsw_options"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_documents_file_path_md5
            ON documents (md5(file_path))
            WHERE file_path IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_documents_file_path_md5",
            table_name="documents",
            postgresql_concurrently=True,
            if_exists=True,
        )
