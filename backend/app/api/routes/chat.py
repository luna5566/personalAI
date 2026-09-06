import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.output_validation import (
    PROVIDER_OUTPUT_TOO_LARGE_PUBLIC_MESSAGE,
    ProviderOutputTooLargeError,
)
from app.api.deps import authenticated_user_id, db_session
from app.core.pagination import (
    CURSOR_MAX_LENGTH,
    MAX_PAGE_NUMBER,
    decode_timestamp_id_cursor,
    encode_timestamp_id_cursor,
)
from app.core.request_limits import DOCUMENT_SEARCH_KEYWORD_MAX_LENGTH
from app.schemas.chat import (
    ChatQueryRequest,
    ChatQueryResponse,
    ConversationListItem,
    ConversationListResponse,
    ConversationRead,
    ConversationUpdate,
    MessageListResponse,
    MessageScanResponse,
)
from app.services import chat_service
from app.services.login_rate_limit_service import ai_user_rate_limiter

router = APIRouter(prefix="/chat", tags=["chat"])
MESSAGE_SCAN_CURSOR_KIND = "chat.messages.created-id.asc"
MESSAGE_RECENT_CURSOR_KIND = "chat.messages.created-id.desc"
AI_RATE_LIMIT_MESSAGE = "请求过于频繁，请稍后再试"


@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE_NUMBER)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[
        str | None,
        Query(max_length=DOCUMENT_SEARCH_KEYWORD_MAX_LENGTH),
    ] = None,
) -> ConversationListResponse:
    items, total = chat_service.list_conversations(
        db,
        user_id,
        page,
        page_size,
        keyword=keyword,
    )
    return ConversationListResponse(
        items=[ConversationListItem.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationRead)
def get_conversation(
    conversation_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> ConversationRead:
    conversation = chat_service.get_conversation(db, user_id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return conversation


@router.get("/conversations/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages(
    conversation_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE_NUMBER)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
) -> MessageListResponse:
    items, total = chat_service.list_messages(
        db,
        user_id,
        conversation_id,
        page,
        page_size,
    )
    return MessageListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/conversations/{conversation_id}/messages/scan",
    response_model=MessageScanResponse,
)
def scan_messages(
    conversation_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: Annotated[
        str | None,
        Query(min_length=1, max_length=CURSOR_MAX_LENGTH),
    ] = None,
) -> MessageScanResponse:
    decoded_cursor = (
        decode_timestamp_id_cursor(
            cursor,
            expected_kind=MESSAGE_SCAN_CURSOR_KIND,
        )
        if cursor is not None
        else None
    )
    items, next_cursor = chat_service.scan_messages(
        db,
        user_id,
        conversation_id,
        page_size=page_size,
        cursor=decoded_cursor,
    )
    return MessageScanResponse(
        items=items,
        next_cursor=(
            encode_timestamp_id_cursor(MESSAGE_SCAN_CURSOR_KIND, next_cursor)
            if next_cursor is not None
            else None
        ),
    )


@router.get(
    "/conversations/{conversation_id}/messages/recent",
    response_model=MessageScanResponse,
)
def scan_recent_messages(
    conversation_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[
        str | None,
        Query(min_length=1, max_length=CURSOR_MAX_LENGTH),
    ] = None,
) -> MessageScanResponse:
    decoded_cursor = (
        decode_timestamp_id_cursor(
            cursor,
            expected_kind=MESSAGE_RECENT_CURSOR_KIND,
        )
        if cursor is not None
        else None
    )
    items, next_cursor = chat_service.scan_recent_messages(
        db,
        user_id,
        conversation_id,
        page_size=page_size,
        cursor=decoded_cursor,
    )
    return MessageScanResponse(
        items=items,
        next_cursor=(
            encode_timestamp_id_cursor(MESSAGE_RECENT_CURSOR_KIND, next_cursor)
            if next_cursor is not None
            else None
        ),
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> ConversationRead:
    conversation = chat_service.update_conversation_title(
        db,
        user_id,
        conversation_id,
        payload.title,
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> Response:
    deleted = chat_service.delete_conversation(db, user_id, conversation_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/query", response_model=ChatQueryResponse)
def query(
    payload: ChatQueryRequest,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> ChatQueryResponse:
    retry_after = ai_user_rate_limiter.consume(db, user_id=user_id)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=AI_RATE_LIMIT_MESSAGE,
            headers={"Retry-After": str(retry_after)},
        )
    try:
        return chat_service.query(db, user_id, payload)
    except chat_service.ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProviderOutputTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=PROVIDER_OUTPUT_TOO_LARGE_PUBLIC_MESSAGE,
        ) from exc


@router.post("/query/stream")
def query_stream(
    payload: ChatQueryRequest,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> StreamingResponse:
    retry_after = ai_user_rate_limiter.consume(db, user_id=user_id)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=AI_RATE_LIMIT_MESSAGE,
            headers={"Retry-After": str(retry_after)},
        )

    def event_stream():
        try:
            for event in chat_service.query_stream(db, user_id, payload):
                event_type = event.get("type", "message")
                yield (
                    f"event: {event_type}\n"
                    f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                )
        except chat_service.ConversationNotFoundError as exc:
            payload_error = {
                "type": "error",
                "message": str(exc),
            }
            yield (
                "event: error\n"
                f"data: {json.dumps(payload_error, ensure_ascii=False)}\n\n"
            )
        except ProviderOutputTooLargeError:
            payload_error = {
                "type": "error",
                "message": PROVIDER_OUTPUT_TOO_LARGE_PUBLIC_MESSAGE,
            }
            yield (
                "event: error\n"
                f"data: {json.dumps(payload_error, ensure_ascii=False)}\n\n"
            )
        except Exception:
            payload_error = {
                "type": "error",
                "message": "提问失败，请稍后重试",
            }
            yield (
                "event: error\n"
                f"data: {json.dumps(payload_error, ensure_ascii=False)}\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
