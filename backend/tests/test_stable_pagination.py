from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.models.auth_registration_invite import AuthRegistrationInvite
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.message import Message
from app.services import (
    chat_service,
    document_service,
    registration_invite_admin_service,
    tag_service,
)


def test_document_list_has_unique_stable_order() -> None:
    db = MagicMock()
    db.scalar.return_value = 0
    db.scalars.return_value = []

    document_service.list_documents(db, uuid4())

    statement = db.scalars.call_args.args[0]
    assert (
        "ORDER BY documents.created_at DESC, documents.id DESC"
        in str(statement)
    )


def test_tag_search_is_applied_before_count_and_pagination() -> None:
    db = MagicMock()
    db.scalar.return_value = 0
    db.scalars.return_value = []

    tag_service.list_tags(
        db,
        uuid4(),
        page=2,
        page_size=20,
        keyword="  计划%_\\  ",
    )

    count_statement = db.scalar.call_args.args[0]
    list_statement = db.scalars.call_args.args[0]
    assert r"%计划\%\_\\%" in count_statement.compile().params.values()
    assert r"%计划\%\_\\%" in list_statement.compile().params.values()
    assert list_statement._offset_clause.value == 20


def test_conversation_and_message_lists_have_unique_stable_order() -> None:
    db = MagicMock()
    db.scalar.side_effect = [0, SimpleNamespace(), 0]
    db.scalars.return_value = []

    chat_service.list_conversations(db, uuid4())
    conversation_statement = db.execute.call_args.args[0]
    assert (
        "ORDER BY conversations.updated_at DESC, conversations.id DESC"
        in str(conversation_statement)
    )

    chat_service.list_messages(db, uuid4(), uuid4())
    message_statement = db.scalars.call_args.args[0]
    assert (
        "ORDER BY messages.created_at ASC, messages.id ASC"
        in str(message_statement)
    )


def test_recent_messages_have_unique_reverse_query_and_forward_response_order() -> None:
    rows = [
        SimpleNamespace(id=uuid4(), created_at=index)
        for index in range(3, 0, -1)
    ]
    db = MagicMock()
    db.scalar.return_value = SimpleNamespace()
    db.scalars.return_value = rows

    messages, cursor = chat_service.scan_recent_messages(
        db,
        uuid4(),
        uuid4(),
        page_size=2,
    )

    statement = db.scalars.call_args.args[0]
    assert "ORDER BY messages.created_at DESC, messages.id DESC" in str(statement)
    assert messages == [rows[1], rows[0]]
    assert cursor is not None
    assert cursor.timestamp == rows[1].created_at
    assert cursor.id == rows[1].id


def test_recent_conversation_history_has_unique_reverse_order() -> None:
    db = MagicMock()
    db.execute.return_value = []

    assert chat_service._conversation_history(db, uuid4()) == []

    statement = db.execute.call_args.args[0]
    assert (
        "ORDER BY messages.created_at DESC, messages.id DESC"
        in str(statement)
    )


def test_list_indexes_match_stable_query_orders() -> None:
    expected = {
        Document: {
            "ix_documents_user_created_id": (
                "user_id",
                "created_at",
                "id",
            ),
        },
        Conversation: {
            "ix_conversations_user_updated_id": (
                "user_id",
                "updated_at",
                "id",
            ),
        },
        Message: {
            "ix_messages_conversation_created_id": (
                "conversation_id",
                "user_id",
                "created_at",
                "id",
            ),
        },
        AuthRegistrationInvite: {
            "ix_auth_registration_invites_created_id": (
                "created_at",
                "id",
            ),
        },
    }

    for model, model_indexes in expected.items():
        indexes = {
            index.name: tuple(column.name for column in index.columns)
            for index in model.__table__.indexes
        }
        for name, columns in model_indexes.items():
            assert indexes[name] == columns

    assert "ix_documents_user_id" not in {
        index.name for index in Document.__table__.indexes
    }
    assert "ix_conversations_user_updated" not in {
        index.name for index in Conversation.__table__.indexes
    }
    assert "ix_messages_conversation_id" not in {
        index.name for index in Message.__table__.indexes
    }
