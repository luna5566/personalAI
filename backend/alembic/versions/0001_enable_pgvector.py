"""enable pgvector extension

Revision ID: 0001_enable_pgvector
Revises:
Create Date: 2026-05-17
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001_enable_pgvector"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_available_extensions
                WHERE name = 'vector'
            ) THEN
                CREATE EXTENSION IF NOT EXISTS vector;
            ELSE
                RAISE NOTICE 'pgvector extension is not available; skipping vector extension setup';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
