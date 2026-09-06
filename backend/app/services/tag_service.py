from uuid import UUID

from sqlalchemy import delete, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.core.pagination import offset_for_page, validate_cursor_page_size
from app.core.request_limits import DOCUMENT_TAG_LIMIT, TAG_NAME_MAX_LENGTH
from app.models.tag import DocumentTag, Tag
from app.utils.sql import escape_like_pattern


class DocumentTagValidationError(ValueError):
    pass


def normalize_tag_name(name: str) -> str:
    return name.strip()[:TAG_NAME_MAX_LENGTH]


def normalize_document_tag_names(tag_names: list[str]) -> list[str]:
    if len(tag_names) > DOCUMENT_TAG_LIMIT:
        raise DocumentTagValidationError(
            f"每份资料最多添加 {DOCUMENT_TAG_LIMIT} 个标签"
        )

    normalized: list[str] = []
    for name in tag_names:
        if not isinstance(name, str):
            raise DocumentTagValidationError("标签名称格式无效")
        value = name.strip()
        if not value:
            raise DocumentTagValidationError("标签名称不能为空")
        if len(value) > TAG_NAME_MAX_LENGTH:
            raise DocumentTagValidationError(
                f"标签名称不能超过 {TAG_NAME_MAX_LENGTH} 个字符"
            )
        if value not in normalized:
            normalized.append(value)
    return normalized


def set_document_tags(db: Session, user_id: UUID, document_id: UUID, tag_names: list[str]) -> list[Tag]:
    normalized = normalize_document_tag_names(tag_names)

    db.execute(delete(DocumentTag).where(DocumentTag.document_id == document_id))
    tags = [get_or_create_tag(db, user_id, name) for name in normalized]
    db.add_all([DocumentTag(document_id=document_id, tag_id=tag.id) for tag in tags])
    db.flush()
    return tags


def get_or_create_tag(db: Session, user_id: UUID, name: str) -> Tag:
    tag = db.scalar(select(Tag).where(Tag.user_id == user_id, Tag.name == name))
    if tag:
        return tag
    tag = Tag(user_id=user_id, name=name)
    db.add(tag)
    db.flush()
    return tag


def list_tags(
    db: Session,
    user_id: UUID,
    page: int = 1,
    page_size: int = 100,
    keyword: str | None = None,
) -> tuple[list[Tag], int]:
    offset = offset_for_page(page, page_size)
    query_stmt = select(Tag).where(Tag.user_id == user_id)
    if keyword and keyword.strip():
        pattern = f"%{escape_like_pattern(keyword.strip())}%"
        query_stmt = query_stmt.where(Tag.name.ilike(pattern, escape="\\"))
    total = db.scalar(
        select(func.count()).select_from(query_stmt.subquery())
    ) or 0
    items = list(
        db.scalars(
            query_stmt.order_by(Tag.name.asc())
            .offset(offset)
            .limit(page_size)
        )
    )
    return items, total


def scan_tags(
    db: Session,
    user_id: UUID,
    *,
    page_size: int = 100,
    cursor: str | None = None,
) -> tuple[list[Tag], str | None]:
    validate_cursor_page_size(page_size)
    statement = select(Tag).where(Tag.user_id == user_id)
    if cursor is not None:
        statement = statement.where(Tag.name > cursor)
    rows = list(
        db.scalars(
            statement.order_by(Tag.name.asc()).limit(page_size + 1)
        )
    )
    items = rows[:page_size]
    next_cursor = items[-1].name if len(rows) > page_size else None
    return items, next_cursor


def update_tag(db: Session, user_id: UUID, tag_id: UUID, name: str, color: str | None = None) -> Tag | None:
    normalized_name = normalize_tag_name(name)
    if not normalized_name:
        return None

    candidates = list(
        db.scalars(
            select(Tag)
            .where(
                Tag.user_id == user_id,
                or_(Tag.id == tag_id, Tag.name == normalized_name),
            )
            .order_by(Tag.id.asc())
            .with_for_update()
        )
    )
    tag = next((candidate for candidate in candidates if candidate.id == tag_id), None)
    if tag is None:
        return None

    existing = next(
        (
            candidate
            for candidate in candidates
            if candidate.id != tag_id and candidate.name == normalized_name
        ),
        None,
    )
    if existing is not None:
        _merge_tags(db, source_tag=tag, target_tag=existing)
        existing.color = color or existing.color
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    tag.name = normalized_name
    tag.color = color
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def delete_tag(db: Session, user_id: UUID, tag_id: UUID) -> bool:
    result = db.execute(
        delete(Tag).where(Tag.id == tag_id, Tag.user_id == user_id)
    )
    if not result.rowcount:
        return False
    db.commit()
    return True


def document_tag_names(db: Session, document_id: UUID) -> list[str]:
    return list(
        db.scalars(
            select(Tag.name)
            .join(DocumentTag, DocumentTag.tag_id == Tag.id)
            .where(DocumentTag.document_id == document_id)
            .order_by(Tag.name.asc())
        )
    )


def _merge_tags(db: Session, source_tag: Tag, target_tag: Tag) -> None:
    source_links = select(
        DocumentTag.document_id,
        literal(target_tag.id),
    ).where(DocumentTag.tag_id == source_tag.id)
    db.execute(
        postgresql_insert(DocumentTag)
        .from_select(["document_id", "tag_id"], source_links)
        .on_conflict_do_nothing(
            index_elements=[
                DocumentTag.document_id,
                DocumentTag.tag_id,
            ]
        )
    )
    db.execute(
        delete(Tag).where(
            Tag.id == source_tag.id,
            Tag.user_id == source_tag.user_id,
        )
    )


def document_ids_for_tags(
    db: Session,
    user_id: UUID,
    tag_names: list[str],
    limit: int | None = None,
) -> list[UUID]:
    normalized = normalize_document_tag_names(tag_names)
    if not normalized:
        return []
    stmt = (
        select(DocumentTag.document_id)
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .where(Tag.user_id == user_id, Tag.name.in_(normalized))
        .distinct()
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt))
