"""rebuild HNSW online with explicit options

Revision ID: 0027_online_hnsw_options
Revises: 0026_chunk_search
Create Date: 2026-07-18
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0027_online_hnsw_options"
down_revision: Union[str, None] = "0026_chunk_search"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None

INDEX_NAME = "ix_chunk_embeddings_embedding_hnsw"
REPLACEMENT_INDEX_NAME = f"{INDEX_NAME}_replacement"
EXPLICIT_OPTIONS = ("m=16", "ef_construction=64")


def upgrade() -> None:
    _replace_index(
        options=EXPLICIT_OPTIONS,
        with_clause=" WITH (m = 16, ef_construction = 64)",
    )


def downgrade() -> None:
    _replace_index(options=(), with_clause="")


def _replace_index(*, options: tuple[str, ...], with_clause: str) -> None:
    with op.get_context().autocommit_block():
        if _index_matches(INDEX_NAME, options):
            _drop_replacement()
            return

        if not _index_matches(REPLACEMENT_INDEX_NAME, options):
            _drop_replacement()
            op.execute(
                f"""
                CREATE INDEX CONCURRENTLY {REPLACEMENT_INDEX_NAME}
                ON chunk_embeddings
                USING hnsw (embedding vector_l2_ops){with_clause}
                """
            )

        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
        op.execute(
            f"ALTER INDEX {REPLACEMENT_INDEX_NAME} RENAME TO {INDEX_NAME}"
        )


def _drop_replacement() -> None:
    op.execute(
        f"DROP INDEX CONCURRENTLY IF EXISTS {REPLACEMENT_INDEX_NAME}"
    )


def _index_matches(name: str, options: tuple[str, ...]) -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                """
                SELECT
                    index_metadata.indisready
                    AND index_metadata.indisvalid
                    AND index_metadata.indislive
                    AND access_method.amname = 'hnsw'
                    AND indexed_column.attname = 'embedding'
                    AND operator_class.opcname = 'vector_l2_ops'
                    AND COALESCE(
                        index_relation.reloptions,
                        ARRAY[]::text[]
                    ) @> CAST(:options AS text[])
                    AND cardinality(
                        COALESCE(
                            index_relation.reloptions,
                            ARRAY[]::text[]
                        )
                    ) = :option_count
                FROM pg_class AS index_relation
                JOIN pg_index AS index_metadata
                  ON index_metadata.indexrelid = index_relation.oid
                JOIN pg_class AS table_relation
                  ON table_relation.oid = index_metadata.indrelid
                JOIN pg_namespace AS table_namespace
                  ON table_namespace.oid = table_relation.relnamespace
                JOIN pg_am AS access_method
                  ON access_method.oid = index_relation.relam
                JOIN pg_attribute AS indexed_column
                  ON indexed_column.attrelid = table_relation.oid
                 AND indexed_column.attnum = index_metadata.indkey[0]
                JOIN pg_opclass AS operator_class
                  ON operator_class.oid = index_metadata.indclass[0]
                WHERE table_namespace.nspname = current_schema()
                  AND table_relation.relname = 'chunk_embeddings'
                  AND index_relation.relname = :name
                """
            ),
            {
                "name": name,
                "options": list(options),
                "option_count": len(options),
            },
        )
    )
