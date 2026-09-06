from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.models.conversation import Conversation
from app.models.document import Document
from app.services import chat_service, document_service
from app.utils.sql import escape_like_pattern


def test_like_pattern_escapes_metacharacters() -> None:
    assert escape_like_pattern(r"100%_done\next") == (
        r"100\%\_done\\next"
    )


def test_document_search_uses_index_prefilter_and_exact_field_recheck() -> None:
    db = MagicMock()
    db.scalar.return_value = 0
    db.scalars.return_value = []

    document_service.list_documents(db, uuid4(), keyword=r"100%_done")

    statement = db.scalars.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert r"%100\%\_done%" in compiled.params.values()
    sql = str(compiled)
    assert sql.count("ILIKE") == 5
    assert sql.count("ESCAPE") == 5


def test_conversation_search_escapes_wildcards() -> None:
    db = MagicMock()
    db.scalar.return_value = 0
    db.execute.return_value = []

    chat_service.list_conversations(db, uuid4(), keyword=r"100%_done")

    statement = db.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert r"%100\%\_done%" in compiled.params.values()
    assert "ESCAPE" in str(compiled)


def test_document_tag_filter_uses_owner_name_unique_index_prefix() -> None:
    db = MagicMock()
    db.scalar.return_value = 0
    db.scalars.return_value = []
    user_id = uuid4()

    document_service.list_documents(db, user_id, tag="学习")

    statement = db.scalars.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "tags.user_id" in sql
    assert "tags.name" in sql
    assert list(compiled.params.values()).count(user_id) == 2


def test_search_indexes_use_trigram_gin() -> None:
    indexes = {index.name: index for index in Document.__table__.indexes}
    document_index = indexes["ix_documents_search_trgm"]
    document_sql = str(
        CreateIndex(document_index).compile(dialect=postgresql.dialect())
    ).lower()
    assert "using gin" in document_sql
    assert "gin_trgm_ops" in document_sql
    assert "coalesce(raw_text, ''::text)" in document_sql
    assert "coalesce(cleaned_text, ''::text)" in document_sql

    conversation_index = next(
        index
        for index in Conversation.__table__.indexes
        if index.name == "ix_conversations_title_trgm"
    )
    conversation_sql = str(
        CreateIndex(conversation_index).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "USING gin (title gin_trgm_ops)" in conversation_sql
