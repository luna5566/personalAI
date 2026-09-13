from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, case, cast, delete, func, literal, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import JSONB, array
from sqlalchemy.orm import Session, load_only, with_expression

from app.core.config import settings
from app.core.pagination import (
    TimestampIdCursor,
    offset_for_page,
    validate_cursor_page_size,
)
from app.core.request_limits import (
    DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH,
    DOCUMENT_FILENAME_MAX_LENGTH,
    DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH,
    DOCUMENT_LIST_SUMMARY_PREVIEW_MAX_LENGTH,
    DOCUMENT_MIME_TYPE_MAX_LENGTH,
    DOCUMENT_SUMMARY_MAX_LENGTH,
    DOCUMENT_TITLE_MAX_LENGTH,
    NOTE_CONTENT_MAX_LENGTH,
    RELATED_DOCUMENT_BODY_QUERY_MAX_LENGTH,
)
from app.models.document import (
    Document,
    DocumentSourceType,
    DocumentStatus,
    document_search_text_expression,
)
from app.models.embedding import ChunkEmbedding
from app.models.tag import DocumentTag, Tag
from app.schemas.document import (
    DocumentStatsRead,
    DocumentUpdate,
    NoteCreate,
    RelatedDocumentRead,
)
from app.services import (
    chunking_service,
    embedding_service,
    enrichment_service,
    retrieval_service,
    storage_deletion_service,
    tag_service,
)
from app.storage import storage_service
from app.utils.sql import escape_like_pattern
from app.utils.text_cleaner import clean_text


class DocumentStorageProvenanceError(RuntimeError):
    pass


class RelatedDocumentNotFoundError(LookupError):
    pass


class RelatedDocumentUnavailableError(RuntimeError):
    pass


class FileDocumentMetadataValidationError(ValueError):
    pass


class NoteContentValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RelatedDocumentSource:
    id: UUID
    status: str
    title: str
    summary: str | None
    body: str | None


@dataclass(frozen=True)
class DocumentStorageReference:
    id: UUID
    file_path: str | None
    storage_backend: str | None
    storage_scope: str | None


@dataclass
class DocumentDetailView:
    id: UUID
    user_id: UUID
    title: str
    source_type: str
    original_filename: str | None
    file_size: int | None
    mime_type: str | None
    content: str | None
    content_source: str | None
    content_offset: int
    content_length: int
    content_truncated: bool
    summary: str | None
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    tags: list[str] = field(default_factory=list)


def validate_note_content(content: str) -> None:
    if not content:
        raise NoteContentValidationError("笔记正文不能为空")
    if len(content) > NOTE_CONTENT_MAX_LENGTH:
        raise NoteContentValidationError(
            f"笔记正文不能超过 {NOTE_CONTENT_MAX_LENGTH} 个字符"
        )


def validate_file_document_metadata(
    *,
    title: str | None = None,
    original_filename: str,
    mime_type: str | None,
) -> None:
    if title is not None and len(title) > DOCUMENT_TITLE_MAX_LENGTH:
        raise FileDocumentMetadataValidationError(
            f"资料标题不能超过 {DOCUMENT_TITLE_MAX_LENGTH} 个字符"
        )
    if len(original_filename) > DOCUMENT_FILENAME_MAX_LENGTH:
        raise FileDocumentMetadataValidationError(
            f"文件名不能超过 {DOCUMENT_FILENAME_MAX_LENGTH} 个字符"
        )
    if mime_type is not None and len(mime_type) > DOCUMENT_MIME_TYPE_MAX_LENGTH:
        raise FileDocumentMetadataValidationError(
            f"MIME 类型不能超过 {DOCUMENT_MIME_TYPE_MAX_LENGTH} 个字符"
        )


def create_note(
    db: Session,
    user_id: UUID,
    payload: NoteCreate,
    *,
    source_type: DocumentSourceType = DocumentSourceType.NOTE,
    metadata: dict | None = None,
) -> Document:
    content = payload.content.strip()
    validate_note_content(content)
    normalized_tags = tag_service.normalize_document_tag_names(payload.tags)
    db.rollback()
    title = payload.title.strip() if payload.title and payload.title.strip() else _title_from_content(content)
    cleaned = clean_text(content)

    document = Document(
        id=uuid4(),
        user_id=user_id,
        title=title,
        source_type=source_type.value,
        raw_text=content,
        cleaned_text=cleaned,
        status=DocumentStatus.CHUNKING.value,
        metadata_={**(metadata or {}), "tags": normalized_tags},
    )
    chunks = chunking_service.build_document_chunks(document)
    embeddings: list[ChunkEmbedding] = embedding_service.generate_chunk_embeddings(
        chunks
    )
    merged_tags = normalized_tags
    try:
        generated = enrichment_service.generate_document_enrichment(
            document,
            chunks,
        )
    except enrichment_service.EnrichmentProviderError as exc:
        enrichment_service.record_enrichment_error(document, exc)
    else:
        merged_tags, _ = enrichment_service.apply_generated_enrichment(
            document,
            generated,
            existing_tags=normalized_tags,
        )
    document.status = DocumentStatus.INDEXED.value
    try:
        db.add(document)
        db.add_all(chunks)
        db.add_all(embeddings)
        db.flush()
        tag_service.set_document_tags(db, user_id, document.id, merged_tags)
        db.commit()
        db.refresh(document)
    except Exception:
        db.rollback()
        raise
    document.tags = sorted(merged_tags)
    return document


def create_file_document(
    db: Session,
    user_id: UUID,
    title: str,
    source_type: DocumentSourceType,
    file_path: str,
    original_filename: str,
    file_size: int,
    mime_type: str | None,
    tags: list[str] | None = None,
) -> Document:
    document = add_file_document(
        db,
        user_id,
        title,
        source_type,
        file_path,
        original_filename,
        file_size,
        mime_type,
        tags,
    )
    db.commit()
    db.refresh(document)
    return document


def add_file_document(
    db: Session,
    user_id: UUID,
    title: str,
    source_type: DocumentSourceType,
    file_path: str,
    original_filename: str,
    file_size: int,
    mime_type: str | None,
    tags: list[str] | None = None,
) -> Document:
    validate_file_document_metadata(
        title=title,
        original_filename=original_filename,
        mime_type=mime_type,
    )
    normalized_tags = tag_service.normalize_document_tag_names(tags or [])
    document = Document(
        user_id=user_id,
        title=title,
        source_type=source_type.value,
        original_filename=original_filename,
        file_path=file_path,
        storage_backend=settings.storage_backend,
        storage_scope=storage_service.current_storage_scope(),
        file_size=file_size,
        mime_type=mime_type,
        status=DocumentStatus.UPLOADED.value,
        metadata_={},
    )
    db.add(document)
    db.flush()
    tag_service.set_document_tags(db, user_id, document.id, normalized_tags)
    return document


def list_documents(
    db: Session,
    user_id: UUID,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    source_type: DocumentSourceType | None = None,
    status: DocumentStatus | None = None,
    tag: str | None = None,
) -> tuple[list[Document], int]:
    offset = offset_for_page(page, page_size)
    stmt = _document_list_statement().where(Document.user_id == user_id)
    stmt = _apply_filters(
        stmt,
        user_id=user_id,
        keyword=keyword,
        source_type=source_type,
        status=status,
        tag=tag,
    )

    total_stmt = select(func.count()).select_from(
        _apply_filters(
            select(Document.id).where(Document.user_id == user_id),
            user_id=user_id,
            keyword=keyword,
            source_type=source_type,
            status=status,
            tag=tag,
        ).subquery()
    )
    total = db.scalar(total_stmt) or 0

    items = list(
        db.scalars(
            stmt.order_by(Document.created_at.desc(), Document.id.desc())
            .offset(offset)
            .limit(page_size)
        )
    )
    return items, total


def scan_documents(
    db: Session,
    user_id: UUID,
    *,
    page_size: int = 100,
    cursor: TimestampIdCursor | None = None,
    keyword: str | None = None,
    source_type: DocumentSourceType | None = None,
    status: DocumentStatus | None = None,
    tag: str | None = None,
) -> tuple[list[Document], TimestampIdCursor | None]:
    validate_cursor_page_size(page_size)
    statement = _apply_filters(
        _document_list_statement().where(Document.user_id == user_id),
        user_id=user_id,
        keyword=keyword,
        source_type=source_type,
        status=status,
        tag=tag,
    )
    if cursor is not None:
        statement = statement.where(
            tuple_(Document.created_at, Document.id)
            < tuple_(cursor.timestamp, cursor.id)
        )
    rows = list(
        db.scalars(
            statement.order_by(Document.created_at.desc(), Document.id.desc())
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


def get_document(db: Session, user_id: UUID, document_id: UUID) -> Document | None:
    return db.scalar(select(Document).where(Document.id == document_id, Document.user_id == user_id))


def get_document_detail(
    db: Session,
    user_id: UUID,
    document_id: UUID,
    *,
    content_offset: int = 0,
    content_limit: int = DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH,
) -> DocumentDetailView | None:
    row = db.execute(
        _document_detail_statement(
            content_offset=content_offset,
            content_limit=content_limit,
        ).where(
            Document.id == document_id,
            Document.user_id == user_id,
        )
    ).one_or_none()
    return _document_detail_view_from_row(row) if row is not None else None


def export_document_markdown(
    db: Session,
    user_id: UUID,
    document_id: UUID,
) -> tuple[str, str] | None:
    """返回 (文件名, Markdown 文本)；资料不存在时返回 None。"""
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == user_id,
        )
    )
    if document is None:
        return None
    cleaned = document.cleaned_text or ""
    raw = document.raw_text or ""
    content = cleaned or raw or (document.summary or "")
    tag_names = tag_service.document_tag_names(db, document.id)
    created = document.created_at
    lines = ["---"]
    lines.append(f'title: "{(document.title or "未命名").replace(chr(34), chr(39))}"')
    lines.append(f"source: {document.source_type}")
    if created is not None:
        lines.append(f"created_at: {created.isoformat()}")
    if tag_names:
        lines.append("tags: [" + ", ".join(tag_names) + "]")
    lines.append("---")
    lines.append("")
    lines.append(content)
    return _markdown_filename(document.title), chr(10).join(lines)


_FILENAME_FORBIDDEN = frozenset(
    '/:*?"<>|' + "".join(chr(code) for code in range(0x20))
)


def _markdown_filename(title: str | None) -> str:
    safe = "".join(
        "_" if char in _FILENAME_FORBIDDEN else char
        for char in (title or "").strip()
    )
    safe = safe.strip(". ") or "document"
    return safe[:80] + ".md"


def to_document_detail_view(
    document: Document,
    *,
    content_offset: int = 0,
    content_limit: int = DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH,
) -> DocumentDetailView:
    cleaned = document.cleaned_text or ""
    raw = document.raw_text or ""
    summary = (document.summary or "")[:DOCUMENT_SUMMARY_MAX_LENGTH]
    full_content = cleaned or raw or summary
    content_length = len(full_content)
    content = (
        full_content[content_offset : content_offset + content_limit] or None
    )
    content_source = (
        "cleaned_text"
        if cleaned
        else "raw_text"
        if raw
        else "summary"
        if summary
        else None
    )
    return DocumentDetailView(
        id=document.id,
        user_id=document.user_id,
        title=document.title,
        source_type=document.source_type,
        original_filename=document.original_filename,
        file_size=document.file_size,
        mime_type=document.mime_type,
        content=content,
        content_source=content_source,
        content_offset=content_offset,
        content_length=content_length,
        content_truncated=(
            content_offset + len(content or "") < content_length
        ),
        summary=summary or None,
        status=document.status,
        error_message=(document.error_message or "")[
            :DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH
        ]
        or None,
        created_at=document.created_at,
        updated_at=document.updated_at,
        tags=list(getattr(document, "tags", [])),
    )


def get_document_reference(
    db: Session,
    user_id: UUID,
    document_id: UUID,
) -> Document | None:
    return db.scalar(
        _document_reference_statement().where(
            Document.id == document_id,
            Document.user_id == user_id,
        )
    )


def list_document_references(
    db: Session,
    user_id: UUID,
    document_ids: list[UUID],
    *,
    limit: int,
) -> list[Document]:
    if not document_ids or limit <= 0:
        return []
    return list(
        db.scalars(
            _document_reference_statement()
            .where(
                Document.user_id == user_id,
                Document.id.in_(document_ids),
                Document.status == DocumentStatus.INDEXED.value,
            )
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(limit)
        )
    )


def get_document_stats(db: Session, user_id: UUID) -> DocumentStatsRead:
    rows = db.execute(
        select(Document.status, func.count())
        .where(Document.user_id == user_id)
        .group_by(Document.status)
    )
    storage_bytes = db.scalar(
        select(func.coalesce(func.sum(Document.file_size), 0)).where(
            Document.user_id == user_id
        )
    )
    return _document_stats_from_counts(
        {status: int(count) for status, count in rows},
        storage_bytes=int(storage_bytes or 0),
    )


def get_document_by_id(db: Session, document_id: UUID) -> Document | None:
    return db.scalar(select(Document).where(Document.id == document_id))


def find_related_documents(
    db: Session,
    user_id: UUID,
    document_id: UUID,
    limit: int = 5,
) -> list[RelatedDocumentRead]:
    try:
        source = _get_related_document_source(db, user_id, document_id)
        if source is None:
            raise RelatedDocumentNotFoundError("资料不存在")
        if source.status != DocumentStatus.INDEXED.value:
            raise RelatedDocumentUnavailableError(
                "资料尚未完成索引，暂时不能查找相关资料"
            )

        query = "\n".join(
            value
            for value in [
                source.title,
                source.summary or "",
                source.body or "",
            ]
            if value.strip()
        )
        source_document_id = source.id
    except Exception:
        db.rollback()
        raise
    db.rollback()
    try:
        retrieved = retrieval_service.vector_search(
            db=db,
            user_id=user_id,
            query=query,
            top_k=max(limit * 4, 12),
            exclude_document_ids=[source_document_id],
        )
    finally:
        db.rollback()

    related: list[RelatedDocumentRead] = []
    seen: set[UUID] = set()
    for item in retrieved:
        if item.document_id in seen:
            continue
        seen.add(item.document_id)
        related.append(
            RelatedDocumentRead(
                document_id=item.document_id,
                title=item.document_title,
                source_type=item.source_type,
                matched_text=item.content[:400],
                score=item.score,
            )
        )
        if len(related) >= limit:
            break
    return related


def update_document(
    db: Session,
    user_id: UUID,
    document_id: UUID,
    payload: DocumentUpdate,
) -> UUID | None:
    values = {}
    if payload.title is not None:
        title = payload.title.strip()
        if title:
            values["title"] = title[:DOCUMENT_TITLE_MAX_LENGTH]

    normalized_tags = None
    if payload.tags is not None:
        normalized_tags = tag_service.normalize_document_tag_names(payload.tags)
        values["metadata_"] = func.jsonb_set(
            Document.metadata_,
            array(["tags"]),
            cast(normalized_tags, JSONB),
            True,
        )

    statement = update(Document).where(
        Document.id == document_id,
        Document.user_id == user_id,
    )
    if values:
        updated_id = db.scalar(
            statement.values(**values).returning(Document.id)
        )
    else:
        updated_id = db.scalar(
            select(Document.id).where(
                Document.id == document_id,
                Document.user_id == user_id,
            )
        )
    if updated_id is None:
        db.rollback()
        return None
    if normalized_tags is not None:
        tag_service.set_document_tags(
            db,
            user_id,
            document_id,
            normalized_tags,
        )
    db.commit()
    return updated_id


def delete_document(db: Session, user_id: UUID, document_id: UUID) -> bool:
    reference = _get_document_storage_reference(db, user_id, document_id)
    if reference is None:
        return False

    if reference.file_path and (
        not reference.storage_backend or not reference.storage_scope
    ):
        raise DocumentStorageProvenanceError(
            "资料缺少存储位置信息，暂时不能删除"
        )
    storage_deletion_service.enqueue_storage_deletion(
        db,
        reference.file_path,
        storage_backend=reference.storage_backend,
        storage_scope=reference.storage_scope,
    )
    result = db.execute(
        delete(Document)
        .where(Document.id == document_id, Document.user_id == user_id)
        .execution_options(synchronize_session=False)
    )
    if not result.rowcount:
        db.rollback()
        return False
    db.commit()
    return True


def _apply_filters(
    stmt: Select,
    user_id: UUID,
    keyword: str | None = None,
    source_type: DocumentSourceType | None = None,
    status: DocumentStatus | None = None,
    tag: str | None = None,
) -> Select:
    if keyword and keyword.strip():
        pattern = f"%{escape_like_pattern(keyword.strip())}%"
        stmt = stmt.where(
            document_search_text_expression().ilike(pattern, escape="\\"),
            or_(
                Document.title.ilike(pattern, escape="\\"),
                Document.raw_text.ilike(pattern, escape="\\"),
                Document.cleaned_text.ilike(pattern, escape="\\"),
                Document.summary.ilike(pattern, escape="\\"),
            )
        )
    if source_type:
        stmt = stmt.where(Document.source_type == source_type.value)
    if status:
        stmt = stmt.where(Document.status == status.value)
    if tag:
        stmt = (
            stmt.join(DocumentTag, DocumentTag.document_id == Document.id)
            .join(Tag, Tag.id == DocumentTag.tag_id)
            .where(Tag.user_id == user_id, Tag.name == tag.strip())
        )
    return stmt


def _document_list_statement() -> Select:
    return select(Document).options(
        load_only(
            Document.id,
            Document.title,
            Document.source_type,
            Document.status,
            Document.created_at,
            Document.updated_at,
            raiseload=True,
        ),
        with_expression(
            Document.summary_preview,
            func.left(
                Document.summary,
                DOCUMENT_LIST_SUMMARY_PREVIEW_MAX_LENGTH,
            ),
        ),
        with_expression(
            Document.error_message_preview,
            func.left(
                Document.error_message,
                DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH,
            ),
        ),
    )


def _document_reference_statement() -> Select:
    return select(Document).options(
        load_only(
            Document.id,
            Document.title,
            Document.status,
            raiseload=True,
        )
    )


def _canonical_document_content_expression():
    return func.coalesce(
        func.nullif(Document.cleaned_text, ""),
        func.nullif(Document.raw_text, ""),
        func.nullif(Document.summary, ""),
        "",
    )


def _document_detail_statement(
    *,
    content_offset: int = 0,
    content_limit: int = DOCUMENT_DETAIL_CONTENT_PAGE_MAX_LENGTH,
) -> Select:
    content = _canonical_document_content_expression()
    content_length = func.char_length(content)
    content_source = case(
        (func.nullif(Document.cleaned_text, "").is_not(None), "cleaned_text"),
        (func.nullif(Document.raw_text, "").is_not(None), "raw_text"),
        (func.nullif(Document.summary, "").is_not(None), "summary"),
        else_=None,
    ).label("content_source")
    return select(
        Document.id,
        Document.user_id,
        Document.title,
        Document.source_type,
        Document.original_filename,
        Document.file_size,
        Document.mime_type,
        func.substr(
            content,
            content_offset + 1,
            content_limit,
        ).label("content"),
        content_source,
        literal(content_offset).label("content_offset"),
        content_length.label("content_length"),
        (content_length > content_offset + content_limit).label(
            "content_truncated"
        ),
        func.left(
            Document.summary,
            DOCUMENT_SUMMARY_MAX_LENGTH,
        ).label("summary"),
        Document.status,
        func.left(
            Document.error_message,
            DOCUMENT_LIST_ERROR_PREVIEW_MAX_LENGTH,
        ).label("error_message"),
        Document.created_at,
        Document.updated_at,
    )


def _document_detail_view_from_row(row) -> DocumentDetailView:
    values = list(row)
    values[7] = values[7] or None
    return DocumentDetailView(*values)


def _related_document_source_statement() -> Select:
    return select(
        Document.id,
        Document.status,
        Document.title,
        func.left(
            Document.summary,
            DOCUMENT_SUMMARY_MAX_LENGTH,
        ).label("summary"),
        func.left(
            func.coalesce(
                func.nullif(Document.cleaned_text, ""),
                Document.raw_text,
                "",
            ),
            RELATED_DOCUMENT_BODY_QUERY_MAX_LENGTH,
        ).label("body"),
    )


def _get_related_document_source(
    db: Session,
    user_id: UUID,
    document_id: UUID,
) -> RelatedDocumentSource | None:
    row = db.execute(
        _related_document_source_statement().where(
            Document.id == document_id,
            Document.user_id == user_id,
        )
    ).one_or_none()
    return RelatedDocumentSource(*row) if row is not None else None


def _document_storage_reference_statement() -> Select:
    return select(
        Document.id,
        Document.file_path,
        Document.storage_backend,
        Document.storage_scope,
    )


def _get_document_storage_reference(
    db: Session,
    user_id: UUID,
    document_id: UUID,
) -> DocumentStorageReference | None:
    row = db.execute(
        _document_storage_reference_statement()
        .where(
            Document.id == document_id,
            Document.user_id == user_id,
        )
        .with_for_update()
    ).one_or_none()
    return DocumentStorageReference(*row) if row is not None else None


def attach_tags(db: Session, documents: list[Document]) -> list[Document]:
    if not documents:
        return documents

    tags_by_document: dict[UUID, list[str]] = {
        document.id: [] for document in documents
    }
    rows = db.execute(
        select(DocumentTag.document_id, Tag.name)
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .where(DocumentTag.document_id.in_(tags_by_document))
        .order_by(DocumentTag.document_id, Tag.name.asc())
    )
    for document_id, tag_name in rows:
        tags_by_document[document_id].append(tag_name)

    for document in documents:
        document.tags = tags_by_document[document.id]
    return documents


def _title_from_content(content: str) -> str:
    first_line = content.strip().splitlines()[0] if content.strip() else "未命名笔记"
    return first_line[:40] or "未命名笔记"


def _document_stats_from_counts(
    counts: dict[str, int],
    storage_bytes: int = 0,
) -> DocumentStatsRead:
    indexed = counts.get(DocumentStatus.INDEXED.value, 0)
    failed = counts.get(DocumentStatus.FAILED.value, 0)
    cancelled = counts.get(DocumentStatus.CANCELLED.value, 0)
    total = sum(counts.values())
    return DocumentStatsRead(
        total=total,
        indexed=indexed,
        processing=max(total - indexed - failed - cancelled, 0),
        failed=failed,
        cancelled=cancelled,
        storage_bytes=max(storage_bytes, 0),
    )
