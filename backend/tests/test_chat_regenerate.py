from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.sql.dml import Delete as _Delete

from app.models.message import Message, MessageRole
from app.schemas.chat import ChatQueryRequest, ChatScope
from app.services import chat_service
from app.services.chat_service import (
    PreparedConversation,
    _persist_conversation_turn,
    _prepare_conversation,
)


def test_regenerate_requires_conversation_id() -> None:
    with pytest.raises(ValidationError, match="regenerate"):
        ChatQueryRequest(question="重新回答", regenerate=True)


def test_regenerate_keeps_conversation_with_empty_turn() -> None:
    db = MagicMock()
    conversation_id = uuid4()
    db.scalar.return_value = SimpleNamespace(
        id=conversation_id, title='会话', scope={}
    )

    prepared = _prepare_conversation(
        db,
        uuid4(),
        ChatQueryRequest(
            conversation_id=conversation_id,
            question="重答一次",
            regenerate=True,
        ),
    )

    assert prepared.regenerate is True
    assert prepared.removed_message_ids == ()
    assert prepared.history == []
    db.add.assert_not_called()


def test_regenerate_trims_trailing_turn_from_history(
    monkeypatch,
) -> None:
    db = MagicMock()
    conversation_id = uuid4()
    assistant_message_id = uuid4()
    user_message_id = uuid4()
    db.scalar.return_value = SimpleNamespace(
        id=conversation_id, title='会话', scope={}
    )
    db.execute.return_value = [
        (assistant_message_id, MessageRole.ASSISTANT.value),
        (user_message_id, MessageRole.USER.value),
    ]
    monkeypatch.setattr(
        chat_service,
        "_conversation_history",
        lambda db, conversation_id, limit=6: [
            ("user", "更早的问题"),
            ("assistant", "更早的回答"),
            ("user", "重答一次"),
            ("assistant", "旧回答"),
        ],
    )

    prepared = _prepare_conversation(
        db,
        uuid4(),
        ChatQueryRequest(
            conversation_id=conversation_id,
            question="重答一次",
            regenerate=True,
        ),
    )

    assert prepared.removed_message_ids == (
        assistant_message_id,
        user_message_id,
    )
    assert prepared.history == [("user", "更早的问题"), ("assistant", "更早的回答")]


def test_regenerate_persist_deletes_old_turn_and_only_adds_answer() -> None:
    db = MagicMock()
    conversation_id = uuid4()
    removed_id = uuid4()
    prepared = PreparedConversation(
        id=conversation_id,
        title="会话",
        scope=ChatScope(),
        history=[],
        is_new=False,
        regenerate=True,
        removed_message_ids=(removed_id,),
    )

    _persist_conversation_turn(
        db,
        user_id=uuid4(),
        prepared=prepared,
        question="重答一次",
        answer="新回答",
        citations=[],
        retrieved_count=0,
    )

    added = [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], Message)
    ]
    assert [message.role for message in added] == [
        MessageRole.ASSISTANT.value
    ]
    executed = [call.args[0] for call in db.execute.call_args_list]
    assert any(isinstance(statement, _Delete) for statement in executed)
    db.commit.assert_called_once()


def test_normal_persist_still_adds_user_and_assistant() -> None:
    db = MagicMock()
    prepared = PreparedConversation(
        id=uuid4(),
        title="会话",
        scope=ChatScope(),
        history=[],
        is_new=True,
    )

    _persist_conversation_turn(
        db,
        user_id=uuid4(),
        prepared=prepared,
        question="新问题",
        answer="回答",
        citations=[],
        retrieved_count=0,
    )

    added = [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], Message)
    ]
    assert [message.role for message in added] == [
        MessageRole.USER.value,
        MessageRole.ASSISTANT.value,
    ]
