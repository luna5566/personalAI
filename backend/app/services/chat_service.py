from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    Text,
    case,
    column,
    delete,
    func,
    literal,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by, array
from sqlalchemy.orm import Session, load_only, with_expression

from app.ai.llm_provider import LLMProvider, get_llm_provider
from app.ai.output_validation import validate_provider_text_length
from app.core.pagination import (
    TimestampIdCursor,
    offset_for_page,
    validate_cursor_page_size,
)
from app.core.request_limits import (
    CHAT_CITATION_LIMIT,
    CHAT_CITATION_TEXT_MAX_LENGTH,
    CHAT_SCOPE_DOCUMENT_LIMIT,
    CHAT_SCOPE_SOURCE_TYPE_LIMIT,
    CHAT_SCOPE_TAG_LIMIT,
    CHAT_ANSWER_MAX_LENGTH,
    CHAT_HISTORY_CONTEXT_MESSAGE_MAX_LENGTH,
    DOCUMENT_TITLE_MAX_LENGTH,
    MESSAGE_LIST_CONTENT_PREVIEW_MAX_LENGTH,
    TAG_NAME_MAX_LENGTH,
)
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.rag.citation_builder import build_citations
from app.rag.context_builder import build_context
from app.schemas.chat import (
    Citation,
    ChatQueryRequest,
    ChatQueryResponse,
    ChatScope,
    normalize_legacy_chat_scope,
)
from app.services import retrieval_service
from app.utils.sql import escape_like_pattern

INSUFFICIENT_CONTEXT_ANSWER = "我在你的资料中没有找到足够依据回答这个问题。可以换个问法，或先补充更相关的资料。"


class ConversationNotFoundError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedConversation:
    id: UUID
    title: str
    scope: ChatScope
    history: list[tuple[str, str]]
    is_new: bool


@dataclass(frozen=True)
class ConversationListItemView:
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


def query(
    db: Session,
    user_id: UUID,
    payload: ChatQueryRequest,
    llm_provider: LLMProvider | None = None,
) -> ChatQueryResponse:
    try:
        prepared = _prepare_conversation(db, user_id, payload)
    finally:
        db.rollback()

    document_ids, tag_names, source_types, created_after = (
        _retrieval_scope_filters(prepared.scope)
    )
    try:
        retrieved = retrieval_service.vector_search(
            db=db,
            user_id=user_id,
            query=_retrieval_query(payload.question, prepared.history),
            top_k=8,
            document_ids=document_ids,
            tag_names=tag_names,
            source_types=source_types,
            created_after=created_after,
        )
    finally:
        db.rollback()
    context = build_context(retrieved)
    citations = build_citations(retrieved[:CHAT_CITATION_LIMIT])

    if retrieved:
        llm_provider = llm_provider or get_llm_provider()
        answer = llm_provider.answer_with_context(
            payload.question,
            context,
            history=prepared.history,
        )
        validate_provider_text_length(
            answer,
            max_length=CHAT_ANSWER_MAX_LENGTH,
            output_name="chat answer",
        )
        suggested_questions = llm_provider.suggested_questions(payload.question, answer)
    else:
        answer = INSUFFICIENT_CONTEXT_ANSWER
        suggested_questions = [
            "帮我整理现有资料里可能相关的主题",
            "我应该补充哪些资料才能回答这个问题？",
        ]

    try:
        _persist_conversation_turn(
            db,
            user_id=user_id,
            prepared=prepared,
            question=payload.question,
            answer=answer,
            citations=[
                citation.model_dump(mode="json") for citation in citations
            ],
            retrieved_count=len(retrieved),
        )
    except Exception:
        db.rollback()
        raise

    return ChatQueryResponse(
        conversation_id=prepared.id,
        answer=answer,
        citations=citations,
        suggested_questions=suggested_questions,
    )


def query_stream(
    db: Session,
    user_id: UUID,
    payload: ChatQueryRequest,
    llm_provider: LLMProvider | None = None,
) -> Iterator[dict]:
    """Yield progressive chat events for SSE.

    Events:
    - meta: conversation_id
    - delta: partial answer text
    - done: final answer, citations, suggested_questions
    - error: public error message
    """
    try:
        prepared = _prepare_conversation(db, user_id, payload)
    finally:
        db.rollback()

    yield {
        "type": "meta",
        "conversation_id": str(prepared.id),
    }

    document_ids, tag_names, source_types, created_after = (
        _retrieval_scope_filters(prepared.scope)
    )
    try:
        retrieved = retrieval_service.vector_search(
            db=db,
            user_id=user_id,
            query=_retrieval_query(payload.question, prepared.history),
            top_k=8,
            document_ids=document_ids,
            tag_names=tag_names,
            source_types=source_types,
            created_after=created_after,
        )
    finally:
        db.rollback()
    context = build_context(retrieved)
    citations = build_citations(retrieved[:CHAT_CITATION_LIMIT])

    if retrieved:
        llm_provider = llm_provider or get_llm_provider()
        answer_parts: list[str] = []
        for delta in llm_provider.stream_answer_with_context(
            payload.question,
            context,
            history=prepared.history,
        ):
            if not delta:
                continue
            answer_parts.append(delta)
            yield {"type": "delta", "text": delta}
        answer = "".join(answer_parts)
        validate_provider_text_length(
            answer,
            max_length=CHAT_ANSWER_MAX_LENGTH,
            output_name="chat answer",
        )
        suggested_questions = llm_provider.suggested_questions(
            payload.question,
            answer,
        )
    else:
        answer = INSUFFICIENT_CONTEXT_ANSWER
        yield {"type": "delta", "text": answer}
        suggested_questions = [
            "帮我整理现有资料里可能相关的主题",
            "我应该补充哪些资料才能回答这个问题？",
        ]

    try:
        _persist_conversation_turn(
            db,
            user_id=user_id,
            prepared=prepared,
            question=payload.question,
            answer=answer,
            citations=[
                citation.model_dump(mode="json") for citation in citations
            ],
            retrieved_count=len(retrieved),
        )
    except Exception:
        db.rollback()
        raise

    yield {
        "type": "done",
        "conversation_id": str(prepared.id),
        "answer": answer,
        "citations": [
            citation.model_dump(mode="json") for citation in citations
        ],
        "suggested_questions": suggested_questions,
    }


def list_conversations(
    db: Session,
    user_id: UUID,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
) -> tuple[list[ConversationListItemView], int]:
    offset = offset_for_page(page, page_size)
    filters = [Conversation.user_id == user_id]
    if keyword and keyword.strip():
        pattern = f"%{escape_like_pattern(keyword.strip())}%"
        filters.append(Conversation.title.ilike(pattern, escape="\\"))
    total = (
        db.scalar(
            select(func.count()).select_from(Conversation).where(*filters)
        )
        or 0
    )
    statement = (
        select(
            Conversation.id,
            Conversation.title,
            Conversation.created_at,
            Conversation.updated_at,
        )
        .where(*filters)
        .order_by(
            Conversation.updated_at.desc(),
            Conversation.id.desc(),
        )
        .offset(offset)
        .limit(page_size)
    )
    rows = db.execute(statement)
    return [ConversationListItemView(*row) for row in rows], total


def get_conversation(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
) -> Conversation | None:
    return db.scalar(
        _conversation_detail_statement().where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )


def _conversation_detail_statement():
    return select(Conversation).options(
        load_only(
            Conversation.id,
            Conversation.title,
            Conversation.created_at,
            Conversation.updated_at,
            raiseload=True,
        ),
        with_expression(
            Conversation.scope_preview,
            _bounded_conversation_scope_expression(),
        ),
    )


def _bounded_conversation_scope_expression():
    recent_days_raw = Conversation.scope["recent_days"]
    recent_days_value = case(
        (
            func.jsonb_typeof(recent_days_raw) == "number",
            recent_days_raw,
        ),
        else_=None,
    )
    return func.jsonb_build_object(
        "document_ids",
        _bounded_scope_string_array(
            "document_ids",
            limit=CHAT_SCOPE_DOCUMENT_LIMIT,
            item_max_length=36,
        ),
        "tags",
        _bounded_scope_string_array(
            "tags",
            limit=CHAT_SCOPE_TAG_LIMIT,
            item_max_length=TAG_NAME_MAX_LENGTH,
        ),
        "source_types",
        _bounded_scope_string_array(
            "source_types",
            limit=CHAT_SCOPE_SOURCE_TYPE_LIMIT,
            item_max_length=32,
        ),
        "recent_days",
        recent_days_value,
    )


def _bounded_scope_string_array(
    key: str,
    *,
    limit: int,
    item_max_length: int,
):
    empty_array = literal([], type_=JSONB)
    raw_array = Conversation.scope[key]
    source = case(
        (func.jsonb_typeof(raw_array) == "array", raw_array),
        else_=empty_array,
    )
    elements = (
        func.jsonb_array_elements(source)
        .table_valued(column("value", JSONB), with_ordinality="ordinality")
        .render_derived(name=f"scope_{key}")
    )
    limited = (
        select(elements.c.value, elements.c.ordinality)
        .where(func.jsonb_typeof(elements.c.value) == "string")
        .order_by(elements.c.ordinality)
        .limit(limit)
        .lateral(f"limited_scope_{key}")
    )
    scalar_text = limited.c.value.op("#>>")(array([], type_=Text))
    return (
        select(
            func.coalesce(
                func.jsonb_agg(
                    aggregate_order_by(
                        func.to_jsonb(
                            func.left(scalar_text, item_max_length)
                        ),
                        limited.c.ordinality,
                    )
                ),
                empty_array,
            )
        )
        .select_from(limited)
        .scalar_subquery()
    )


def list_messages(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[Message], int]:
    offset = offset_for_page(page, page_size)
    if not _conversation_exists(db, user_id, conversation_id):
        return [], 0

    filters = (
        Message.conversation_id == conversation_id,
        Message.user_id == user_id,
    )
    total = db.scalar(
        select(func.count()).select_from(Message).where(*filters)
    ) or 0
    items = list(
        db.scalars(
            _message_list_statement()
            .where(*filters)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .offset(offset)
            .limit(page_size)
        )
    )
    return items, total


def scan_messages(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
    *,
    page_size: int = 100,
    cursor: TimestampIdCursor | None = None,
) -> tuple[list[Message], TimestampIdCursor | None]:
    validate_cursor_page_size(page_size)
    if not _conversation_exists(db, user_id, conversation_id):
        return [], None

    statement = _message_list_statement().where(
        Message.conversation_id == conversation_id,
        Message.user_id == user_id,
    )
    if cursor is not None:
        statement = statement.where(
            tuple_(Message.created_at, Message.id)
            > tuple_(cursor.timestamp, cursor.id)
        )
    rows = list(
        db.scalars(
            statement.order_by(Message.created_at.asc(), Message.id.asc())
            .limit(page_size + 1)
        )
    )
    items = rows[:page_size]
    next_cursor = (
        TimestampIdCursor(timestamp=items[-1].created_at, id=items[-1].id)
        if len(rows) > page_size
        else None
    )
    return items, next_cursor


def scan_recent_messages(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
    *,
    page_size: int = 50,
    cursor: TimestampIdCursor | None = None,
) -> tuple[list[Message], TimestampIdCursor | None]:
    validate_cursor_page_size(page_size)
    if not _conversation_exists(db, user_id, conversation_id):
        return [], None

    statement = _message_list_statement().where(
        Message.conversation_id == conversation_id,
        Message.user_id == user_id,
    )
    if cursor is not None:
        statement = statement.where(
            tuple_(Message.created_at, Message.id)
            < tuple_(cursor.timestamp, cursor.id)
        )
    rows = list(
        db.scalars(
            statement.order_by(Message.created_at.desc(), Message.id.desc())
            .limit(page_size + 1)
        )
    )
    page_descending = rows[:page_size]
    next_cursor = (
        TimestampIdCursor(
            timestamp=page_descending[-1].created_at,
            id=page_descending[-1].id,
        )
        if len(rows) > page_size
        else None
    )
    page_descending.reverse()
    return page_descending, next_cursor


def update_conversation_title(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
    title: str,
) -> Conversation | None:
    updated_id = db.scalar(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        .values(
            title=" ".join(title.strip().split())[:255],
            updated_at=datetime.now(timezone.utc),
        )
        .returning(Conversation.id)
    )
    if updated_id is None:
        return None
    db.commit()
    return get_conversation(db, user_id, updated_id)


def delete_conversation(db: Session, user_id: UUID, conversation_id: UUID) -> bool:
    deleted_id = db.scalar(
        delete(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        .returning(Conversation.id)
    )
    if deleted_id is None:
        return False
    db.commit()
    return True


def _prepare_conversation(
    db: Session,
    user_id: UUID,
    payload: ChatQueryRequest,
) -> PreparedConversation:
    if payload.conversation_id:
        conversation = db.scalar(
            _conversation_detail_statement().where(
                Conversation.id == payload.conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if conversation is None:
            raise ConversationNotFoundError("会话不存在或已被删除")
        scope = _effective_scope(conversation, payload)
        return PreparedConversation(
            id=conversation.id,
            title=conversation.title,
            scope=scope,
            history=_conversation_history(db, conversation.id),
            is_new=False,
        )

    return PreparedConversation(
        id=uuid4(),
        title=_title_from_question(payload.question),
        scope=payload.scope or ChatScope(),
        history=[],
        is_new=True,
    )


def _persist_conversation_turn(
    db: Session,
    *,
    user_id: UUID,
    prepared: PreparedConversation,
    question: str,
    answer: str,
    citations: list[dict],
    retrieved_count: int,
) -> None:
    bounded_citations = [
        Citation.model_validate(citation).model_dump(mode="json")
        for citation in citations[:CHAT_CITATION_LIMIT]
    ]
    if prepared.is_new:
        conversation = Conversation(
            id=prepared.id,
            user_id=user_id,
            title=prepared.title,
            scope=prepared.scope.model_dump(mode="json"),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(conversation)
    else:
        locked_id = db.scalar(
            select(Conversation.id)
            .where(
                Conversation.id == prepared.id,
                Conversation.user_id == user_id,
            )
            .with_for_update()
        )
        if locked_id is None:
            raise ConversationNotFoundError("会话不存在或已被删除")
        db.execute(
            update(Conversation)
            .where(
                Conversation.id == locked_id,
                Conversation.user_id == user_id,
            )
            .values(
                scope=prepared.scope.model_dump(mode="json"),
                updated_at=datetime.now(timezone.utc),
            )
        )
    db.add(
        Message(
            conversation_id=prepared.id,
            user_id=user_id,
            role=MessageRole.USER.value,
            content=question.strip(),
            citations=[],
            metadata_={},
        )
    )
    db.add(
        Message(
            conversation_id=prepared.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT.value,
            content=answer,
            citations=bounded_citations,
            metadata_={"retrieved_count": retrieved_count},
        )
    )
    db.commit()


def _title_from_question(question: str) -> str:
    compact = " ".join(question.strip().split())
    return compact[:40] or "新会话"


def _effective_scope(conversation: Conversation, payload: ChatQueryRequest) -> ChatScope:
    if payload.scope is not None:
        return payload.scope
    if not payload.conversation_id:
        return ChatScope()
    projected_scope = getattr(conversation, "scope_preview", None)
    source_attribute = "scope_preview" if projected_scope is not None else "scope"
    value = (
        projected_scope
        if projected_scope is not None
        else getattr(conversation, "scope", {})
    )
    try:
        return ChatScope.model_validate(value or {})
    except ValueError:
        scope = _bounded_legacy_scope(value or {})
        setattr(conversation, source_attribute, scope.model_dump(mode="json"))
        return scope


def _bounded_legacy_scope(value: dict) -> ChatScope:
    return ChatScope.model_validate(normalize_legacy_chat_scope(value))


def _retrieval_scope_filters(
    scope: ChatScope,
) -> tuple[
    list[UUID] | None,
    list[str] | None,
    list[str] | None,
    datetime | None,
]:
    document_ids = list(scope.document_ids) if scope.document_ids else None
    tag_names = list(scope.tags) if scope.tags else None
    source_types = (
        [source_type.value for source_type in scope.source_types]
        if scope.source_types
        else None
    )
    created_after = retrieval_service.created_after_from_recent_days(
        scope.recent_days
    )
    return document_ids, tag_names, source_types, created_after


def _conversation_history(db: Session, conversation_id: UUID, limit: int = 6) -> list[tuple[str, str]]:
    recent = list(
        db.execute(
            select(
                Message.role,
                func.left(
                    Message.content,
                    CHAT_HISTORY_CONTEXT_MESSAGE_MAX_LENGTH,
                ),
            )
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
    )
    recent.reverse()
    return [
        (role, content)
        for role, content in recent
        if role in {MessageRole.USER.value, MessageRole.ASSISTANT.value}
    ]


def _conversation_exists(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
) -> bool:
    return (
        db.scalar(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        is not None
    )


def _message_list_statement():
    return select(Message).options(
        load_only(
            Message.id,
            Message.conversation_id,
            Message.role,
            Message.created_at,
            raiseload=True,
        ),
        with_expression(
            Message.content_preview,
            func.left(
                Message.content,
                MESSAGE_LIST_CONTENT_PREVIEW_MAX_LENGTH,
            ),
        ),
        with_expression(
            Message.content_truncated,
            func.length(Message.content)
            > MESSAGE_LIST_CONTENT_PREVIEW_MAX_LENGTH,
        ),
        with_expression(
            Message.citations_preview,
            _bounded_message_citations_expression(),
        ),
    )


def _bounded_message_citations_expression():
    empty_array = literal([], type_=JSONB)
    source = case(
        (func.jsonb_typeof(Message.citations) == "array", Message.citations),
        else_=empty_array,
    )
    elements = (
        func.jsonb_array_elements(source)
        .table_valued(column("value", JSONB), with_ordinality="ordinality")
        .render_derived(name="citation_elements")
    )
    limited = (
        select(elements.c.value, elements.c.ordinality)
        .where(func.jsonb_typeof(elements.c.value) == "object")
        .order_by(elements.c.ordinality)
        .limit(CHAT_CITATION_LIMIT)
        .lateral("limited_citations")
    )
    value = limited.c.value
    bounded = func.jsonb_build_object(
        "document_id",
        func.left(value["document_id"].astext, 36),
        "document_title",
        func.left(value["document_title"].astext, DOCUMENT_TITLE_MAX_LENGTH),
        "source_type",
        func.left(value["source_type"].astext, 32),
        "chunk_id",
        func.left(value["chunk_id"].astext, 36),
        "chunk_index",
        func.left(value["chunk_index"].astext, 32),
        "text",
        func.left(value["text"].astext, CHAT_CITATION_TEXT_MAX_LENGTH),
        "score",
        func.left(value["score"].astext, 32),
        "start_offset",
        func.left(value["start_offset"].astext, 32),
        "end_offset",
        func.left(value["end_offset"].astext, 32),
        "page_number",
        func.left(value["page_number"].astext, 32),
        "section_title",
        func.left(value["section_title"].astext, DOCUMENT_TITLE_MAX_LENGTH),
    )
    return (
        select(
            func.coalesce(
                func.jsonb_agg(
                    aggregate_order_by(bounded, limited.c.ordinality)
                ),
                empty_array,
            )
        )
        .select_from(limited)
        .scalar_subquery()
    )


def _retrieval_query(question: str, history: list[tuple[str, str]]) -> str:
    previous = [content.strip()[:500] for _, content in history[-4:] if content.strip()]
    if not previous:
        return question
    return f"{question}\n\n最近对话：\n" + "\n".join(previous)
