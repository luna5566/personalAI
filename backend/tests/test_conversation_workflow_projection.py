from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.core.request_limits import (
    CHAT_CITATION_LIMIT,
    CHAT_SCOPE_DOCUMENT_LIMIT,
    CHAT_SCOPE_SOURCE_TYPE_LIMIT,
    CHAT_SCOPE_TAG_LIMIT,
    TAG_NAME_MAX_LENGTH,
)
from app.schemas.chat import ConversationListResponse, ConversationRead
from app.services import chat_service


def test_conversation_list_uses_narrow_rows_without_scope() -> None:
    now = datetime.now(UTC)
    conversation_id = uuid4()
    db = MagicMock()
    db.scalar.return_value = 1
    db.execute.return_value = [
        (conversation_id, "会话", now, now),
    ]

    items, total = chat_service.list_conversations(db, uuid4())

    assert total == 1
    assert items[0].id == conversation_id
    statement = db.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    select_clause = str(compiled).split("FROM conversations", maxsplit=1)[0]
    assert "conversations.id" in select_clause
    assert "conversations.title" in select_clause
    assert "conversations.created_at" in select_clause
    assert "conversations.updated_at" in select_clause
    assert "conversations.scope" not in select_clause
    assert "conversations.user_id" not in select_clause

    payload = ConversationListResponse(
        items=items,
        total=total,
        page=1,
        page_size=20,
    ).model_dump(mode="json")
    assert "scope" not in payload["items"][0]


def test_conversation_detail_projects_bounded_structured_scope() -> None:
    compiled = chat_service._conversation_detail_statement().compile(
        dialect=postgresql.dialect()
    )
    select_clause = str(compiled).split("FROM conversations", maxsplit=1)[0]
    values = list(compiled.params.values())

    assert select_clause.count("jsonb_array_elements") == 3
    assert "jsonb_build_object" in select_clause
    assert "WITH ORDINALITY" in select_clause
    assert CHAT_SCOPE_DOCUMENT_LIMIT in values
    assert CHAT_SCOPE_TAG_LIMIT in values
    assert CHAT_SCOPE_SOURCE_TYPE_LIMIT in values
    assert 36 in values
    assert TAG_NAME_MAX_LENGTH in values
    assert 32 in values
    assert "conversations.scope AS scope" not in select_clause
    assert "conversations.user_id" not in select_clause


def test_conversation_read_normalizes_invalid_projected_scope() -> None:
    now = datetime.now(UTC)
    valid_document_id = uuid4()
    source = SimpleNamespace(
        id=uuid4(),
        title="会话",
        scope_preview={
            "document_ids": [str(valid_document_id), "invalid"],
            "tags": ["  学习  ", "x" * (TAG_NAME_MAX_LENGTH + 1), 42],
            "source_types": ["note", "invalid"],
        },
        created_at=now,
        updated_at=now,
    )

    payload = ConversationRead.model_validate(source).model_dump(mode="json")

    assert payload["scope"] == {
        "document_ids": [str(valid_document_id)],
        "tags": ["学习", "x" * TAG_NAME_MAX_LENGTH],
        "source_types": ["note"],
        "recent_days": None,
    }


def test_message_ownership_check_selects_only_conversation_id() -> None:
    conversation_id = uuid4()
    db = MagicMock()
    db.scalar.side_effect = [conversation_id, 0]
    db.scalars.return_value = []

    items, total = chat_service.list_messages(
        db,
        uuid4(),
        conversation_id,
    )

    assert items == []
    assert total == 0
    ownership_statement = db.scalar.call_args_list[0].args[0]
    select_clause = str(
        ownership_statement.compile(dialect=postgresql.dialect())
    ).split("FROM conversations", maxsplit=1)[0]
    assert "conversations.id" in select_clause
    assert "conversations.scope" not in select_clause
    assert "conversations.title" not in select_clause


def test_conversation_title_update_is_set_based() -> None:
    conversation_id = uuid4()
    updated = SimpleNamespace(id=conversation_id)
    db = MagicMock()
    db.scalar.side_effect = [conversation_id, updated]

    result = chat_service.update_conversation_title(
        db,
        uuid4(),
        conversation_id,
        "  新   标题  ",
    )

    assert result is updated
    statement = db.scalar.call_args_list[0].args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert sql.startswith("UPDATE conversations SET")
    assert "RETURNING conversations.id" in sql
    assert "conversations.scope" not in sql
    assert "新 标题" in compiled.params.values()
    db.add.assert_not_called()
    db.commit.assert_called_once_with()


def test_conversation_delete_is_set_based_and_relies_on_database_cascade() -> None:
    conversation_id = uuid4()
    db = MagicMock()
    db.scalar.return_value = conversation_id

    deleted = chat_service.delete_conversation(
        db,
        uuid4(),
        conversation_id,
    )

    assert deleted is True
    statement = db.scalar.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert sql.startswith("DELETE FROM conversations")
    assert "RETURNING conversations.id" in sql
    db.delete.assert_not_called()
    db.commit.assert_called_once_with()


def test_existing_turn_locks_only_id_and_updates_scope_without_loading_it() -> None:
    conversation_id = uuid4()
    user_id = uuid4()
    db = MagicMock()
    db.scalar.return_value = conversation_id
    prepared = chat_service.PreparedConversation(
        id=conversation_id,
        title="会话",
        scope=chat_service.ChatScope(tags=["学习"]),
        history=[],
        is_new=False,
    )

    chat_service._persist_conversation_turn(
        db,
        user_id=user_id,
        prepared=prepared,
        question="继续",
        answer="回答",
        citations=[],
        retrieved_count=0,
    )

    lock_statement = db.scalar.call_args.args[0]
    lock_sql = str(lock_statement.compile(dialect=postgresql.dialect()))
    lock_select = lock_sql.split("FROM conversations", maxsplit=1)[0]
    assert "conversations.id" in lock_select
    assert "conversations.scope" not in lock_select
    assert "FOR UPDATE" in lock_sql

    update_statement = db.execute.call_args.args[0]
    compiled_update = update_statement.compile(dialect=postgresql.dialect())
    assert str(compiled_update).startswith("UPDATE conversations SET")
    assert {"document_ids": [], "tags": ["学习"], "source_types": [], "recent_days": None} in (
        compiled_update.params.values()
    )
    assert db.add.call_count == 2
    db.commit.assert_called_once_with()


def test_new_turn_bounds_citations_before_persistence() -> None:
    db = MagicMock()
    prepared = chat_service.PreparedConversation(
        id=uuid4(),
        title="会话",
        scope=chat_service.ChatScope(),
        history=[],
        is_new=True,
    )
    citations = [
        {
            "document_id": str(uuid4()),
            "document_title": f"资料 {index}",
            "source_type": "note",
            "chunk_id": str(uuid4()),
            "chunk_index": index,
            "text": "引用",
            "score": 0.8,
            "start_offset": index,
            "end_offset": index + 1,
            "page_number": None,
            "section_title": None,
        }
        for index in range(CHAT_CITATION_LIMIT + 1)
    ]

    chat_service._persist_conversation_turn(
        db,
        user_id=uuid4(),
        prepared=prepared,
        question="问题",
        answer="回答",
        citations=citations,
        retrieved_count=len(citations),
    )

    assistant = next(
        call.args[0]
        for call in db.add.call_args_list
        if getattr(call.args[0], "role", None) == "assistant"
    )
    assert len(assistant.citations) == CHAT_CITATION_LIMIT
    assert assistant.citations[-1]["document_title"] == "资料 7"
