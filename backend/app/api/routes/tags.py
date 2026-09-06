from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import authenticated_user_id, db_session
from app.core.pagination import (
    CURSOR_MAX_LENGTH,
    MAX_PAGE_NUMBER,
    decode_text_cursor,
    encode_text_cursor,
)
from app.core.request_limits import TAG_NAME_MAX_LENGTH
from app.schemas.tag import TagRead, TagScanResponse, TagUpdate
from app.services import tag_service

router = APIRouter(prefix="/tags", tags=["tags"])
TAG_SCAN_CURSOR_KIND = "tags.name.asc"


@router.get("", response_model=list[TagRead])
def list_tags(
    response: Response,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE_NUMBER)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
    keyword: Annotated[
        str | None,
        Query(max_length=TAG_NAME_MAX_LENGTH),
    ] = None,
) -> list[TagRead]:
    items, total = tag_service.list_tags(
        db,
        user_id,
        page,
        page_size,
        keyword=keyword,
    )
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get("/scan", response_model=TagScanResponse)
def scan_tags(
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: Annotated[
        str | None,
        Query(min_length=1, max_length=CURSOR_MAX_LENGTH),
    ] = None,
) -> TagScanResponse:
    decoded_cursor = (
        decode_text_cursor(
            cursor,
            expected_kind=TAG_SCAN_CURSOR_KIND,
            max_value_length=TAG_NAME_MAX_LENGTH,
        )
        if cursor is not None
        else None
    )
    items, next_cursor = tag_service.scan_tags(
        db,
        user_id,
        page_size=page_size,
        cursor=decoded_cursor,
    )
    return TagScanResponse(
        items=items,
        next_cursor=(
            encode_text_cursor(TAG_SCAN_CURSOR_KIND, next_cursor)
            if next_cursor is not None
            else None
        ),
    )


@router.patch("/{tag_id}", response_model=TagRead)
def update_tag(
    tag_id: UUID,
    payload: TagUpdate,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> TagRead:
    tag = tag_service.update_tag(db, user_id, tag_id, payload.name, payload.color)
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="标签不存在")
    return tag


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> None:
    deleted = tag_service.delete_tag(db, user_id, tag_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="标签不存在")
