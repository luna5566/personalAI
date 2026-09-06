from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.ai.llm_provider import _chat_messages
from app.core.request_limits import (
    CHAT_SCOPE_DOCUMENT_LIMIT,
    CHAT_SCOPE_SOURCE_TYPE_LIMIT,
    CHAT_SCOPE_TAG_LIMIT,
    TAG_NAME_MAX_LENGTH,
)
from app.schemas.chat import ChatQueryRequest, ChatScope
from app.services import chat_service
from app.services.chat_service import (
    ConversationNotFoundError,
    _effective_scope,
    _prepare_conversation,
    _retrieval_scope_filters,
    _retrieval_query,
)
from app.services.retrieval_service import RetrievedChunk, _filter_relevant_chunks


class ChatBoundarySession:
    def __init__(self, scalar_results=()) -> None:
        self.scalar_results = iter(scalar_results)
        self.connection_checked_out = True
        self.events = []
        self.added = []
        self.scalar_statements = []

    def scalar(self, statement):
        self.connection_checked_out = True
        self.events.append("scalar")
        self.scalar_statements.append(statement)
        return next(self.scalar_results)

    def scalars(self, statement):
        self.connection_checked_out = True
        self.events.append("scalars")
        return []

    def execute(self, statement):
        self.connection_checked_out = True
        self.events.append("execute")
        return []

    def rollback(self):
        self.events.append("rollback")
        self.connection_checked_out = False

    def add(self, value):
        self.events.append("add")
        self.added.append(value)

    def commit(self):
        self.events.append("commit")
        self.connection_checked_out = False


def test_retrieval_query_includes_recent_conversation() -> None:
    query = _retrieval_query(
        "它有什么限制？",
        [("user", "介绍一下本地 hash embedding"), ("assistant", "它用于本地联调。")],
    )

    assert query.startswith("它有什么限制？")
    assert "本地 hash embedding" in query
    assert "本地联调" in query


def test_chat_messages_include_only_recent_supported_roles() -> None:
    history = [
        ("system", "ignore"),
        ("user", "第一个问题"),
        ("assistant", "第一个回答"),
        ("user", "第二个问题"),
    ]

    messages = _chat_messages("继续", "资料内容", history)

    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "user",
        "user",
    ]
    assert messages[-1]["content"].startswith("当前问题：继续")


def test_scope_filters_are_forwarded_without_resolving_document_ids() -> None:
    document_id = uuid4()

    document_ids, tag_names, source_types, created_after = _retrieval_scope_filters(
        ChatScope(
            document_ids=[document_id],
            tags=["学习"],
            source_types=["note"],
        )
    )

    assert document_ids == [document_id]
    assert tag_names == ["学习"]
    assert source_types == ["note"]
    assert created_after is None


def test_low_relevance_chunks_are_not_used_for_answers() -> None:
    document_id = uuid4()
    low = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        document_title="无关资料",
        source_type="note",
        chunk_index=0,
        content="无关内容",
        start_offset=0,
        end_offset=4,
        score=0.34,
    )
    high = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        document_title="相关资料",
        source_type="note",
        chunk_index=1,
        content="相关内容",
        start_offset=5,
        end_offset=9,
        score=0.72,
    )

    assert _filter_relevant_chunks([low, high]) == [high]


def test_conversation_search_is_applied_before_pagination() -> None:
    db = MagicMock()
    db.scalar.return_value = 0
    db.execute.return_value = []

    chat_service.list_conversations(
        db,
        uuid4(),
        page=2,
        page_size=20,
        keyword="  学习  ",
    )

    statement = db.execute.call_args.args[0]
    compiled = statement.compile()
    assert "%学习%" in compiled.params.values()
    assert statement._offset_clause.value == 20


def test_missing_conversation_is_not_silently_recreated() -> None:
    db = MagicMock()
    db.scalar.return_value = None

    with pytest.raises(ConversationNotFoundError, match="会话不存在"):
        _prepare_conversation(
            db,
            uuid4(),
            ChatQueryRequest(
                conversation_id=uuid4(),
                question="继续提问",
                scope=ChatScope(),
            ),
        )

    db.add.assert_not_called()


def test_explicit_empty_scope_clears_a_conversation_scope() -> None:
    conversation = SimpleNamespace(scope={"tags": ["旧标签"]})
    request = ChatQueryRequest(
        conversation_id=uuid4(),
        question="改为全部资料",
        scope=ChatScope(),
    )

    scope = _effective_scope(conversation, request)

    assert scope.document_ids == []
    assert scope.tags == []
    assert scope.source_types == []


def test_oversized_legacy_scope_is_bounded_and_rewritten() -> None:
    document_ids = [uuid4() for _ in range(CHAT_SCOPE_DOCUMENT_LIMIT + 1)]
    conversation = SimpleNamespace(
        scope={
            "document_ids": [str(document_id) for document_id in document_ids],
            "tags": [
                "x" * (TAG_NAME_MAX_LENGTH + 1)
                for _ in range(CHAT_SCOPE_TAG_LIMIT + 1)
            ],
            "source_types": [
                "note" for _ in range(CHAT_SCOPE_SOURCE_TYPE_LIMIT + 1)
            ],
        }
    )
    request = ChatQueryRequest(
        conversation_id=uuid4(),
        question="继续提问",
    )

    scope = _effective_scope(conversation, request)

    assert scope.document_ids == document_ids[:CHAT_SCOPE_DOCUMENT_LIMIT]
    assert len(scope.tags) == CHAT_SCOPE_TAG_LIMIT
    assert scope.tags == ["x" * TAG_NAME_MAX_LENGTH] * CHAT_SCOPE_TAG_LIMIT
    assert len(scope.source_types) == CHAT_SCOPE_SOURCE_TYPE_LIMIT
    assert conversation.scope == scope.model_dump(mode="json")


def test_chat_releases_database_connection_during_provider_calls(
    monkeypatch,
) -> None:
    db = ChatBoundarySession()
    retrieved = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title="资料",
        source_type="note",
        chunk_index=0,
        content="相关内容",
        start_offset=0,
        end_offset=4,
        score=0.8,
    )

    def search(**kwargs):
        assert db.connection_checked_out is False
        db.connection_checked_out = True
        return [retrieved]

    class Provider:
        def answer_with_context(self, question, context, history):
            assert db.connection_checked_out is False
            return "回答"

        def suggested_questions(self, question, answer):
            assert db.connection_checked_out is False
            return ["继续"]

    monkeypatch.setattr(chat_service.retrieval_service, "vector_search", search)

    result = chat_service.query(
        db,
        uuid4(),
        ChatQueryRequest(question="问题"),
        llm_provider=Provider(),
    )

    assert result.answer == "回答"
    assert db.events[:2] == ["rollback", "rollback"]
    assert db.events[-1] == "commit"
    assert len(db.added) == 3
    messages = [value for value in db.added if hasattr(value, "role")]
    assert [message.role for message in messages] == ["user", "assistant"]


@pytest.mark.parametrize("failure_stage", ["retrieval", "llm"])
def test_chat_provider_failure_does_not_persist_a_partial_turn(
    monkeypatch,
    failure_stage,
) -> None:
    db = ChatBoundarySession()

    def search(**kwargs):
        assert db.connection_checked_out is False
        db.connection_checked_out = True
        if failure_stage == "retrieval":
            raise RuntimeError("retrieval failed")
        return [
            RetrievedChunk(
                chunk_id=uuid4(),
                document_id=uuid4(),
                document_title="资料",
                source_type="note",
                chunk_index=0,
                content="相关内容",
                start_offset=0,
                end_offset=4,
                score=0.8,
            )
        ]

    class Provider:
        def answer_with_context(self, question, context, history):
            assert db.connection_checked_out is False
            raise RuntimeError("llm failed")

    monkeypatch.setattr(chat_service.retrieval_service, "vector_search", search)

    with pytest.raises(RuntimeError, match=failure_stage):
        chat_service.query(
            db,
            uuid4(),
            ChatQueryRequest(question="问题"),
            llm_provider=Provider(),
        )

    assert db.added == []
    assert "commit" not in db.events
    assert db.connection_checked_out is False


def test_existing_conversation_is_rechecked_before_persisting(
    monkeypatch,
) -> None:
    conversation_id = uuid4()
    existing = SimpleNamespace(
        id=conversation_id,
        title="会话",
        scope={},
    )
    db = ChatBoundarySession([existing, None])

    def search(**kwargs):
        assert db.connection_checked_out is False
        db.connection_checked_out = True
        return []

    monkeypatch.setattr(chat_service.retrieval_service, "vector_search", search)

    with pytest.raises(ConversationNotFoundError, match="会话不存在"):
        chat_service.query(
            db,
            uuid4(),
            ChatQueryRequest(
                conversation_id=conversation_id,
                question="继续",
            ),
        )

    assert db.added == []
    assert "commit" not in db.events
    assert "FOR UPDATE" in str(db.scalar_statements[-1])
    assert db.connection_checked_out is False
