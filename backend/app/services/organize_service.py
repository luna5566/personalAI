from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm_provider import LLMProvider, get_llm_provider
from app.ai.output_validation import validate_provider_text_length
from app.core.request_limits import ORGANIZE_RESULT_MAX_LENGTH
from app.models.document import Document, DocumentSourceType, DocumentStatus
from app.schemas.document import NoteCreate
from app.schemas.organize import (
    OrganizeCollectionRequest,
    OrganizeDocumentRequest,
    OrganizeResponse,
    OrganizeResultSaveRequest,
    OrganizeResultSaveResponse,
)
from app.services import context_chunk_service, document_service, tag_service
from app.services.context_chunk_service import ContextChunk

MAX_COLLECTION_DOCUMENTS = 20
MAX_ORGANIZE_CONTEXT_CHARS = 24_000


class OrganizeNotFoundError(ValueError):
    pass


class OrganizeConflictError(ValueError):
    pass


class OrganizeValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedOrganization:
    context: str
    source_document_ids: list[UUID]
    note_title: str


def organize_document(
    db: Session,
    user_id: UUID,
    payload: OrganizeDocumentRequest,
    llm_provider: LLMProvider | None = None,
) -> OrganizeResponse:
    try:
        prepared = _prepare_document_organization(db, user_id, payload)
    except Exception:
        db.rollback()
        raise
    db.rollback()
    provider = llm_provider or get_llm_provider()
    result = provider.organize_with_context(payload.mode.value, prepared.context)
    validate_provider_text_length(
        result,
        max_length=ORGANIZE_RESULT_MAX_LENGTH,
        output_name="organization result",
    )

    saved_document_id = None
    if payload.save_as_note:
        saved = _save_result_note(
            db=db,
            user_id=user_id,
            title=prepared.note_title,
            result=result,
            source_document_ids=prepared.source_document_ids,
        )
        saved_document_id = saved.id

    return OrganizeResponse(
        mode=payload.mode.value,
        result=result,
        source_document_ids=prepared.source_document_ids,
        saved_document_id=saved_document_id,
    )


def _prepare_document_organization(
    db: Session,
    user_id: UUID,
    payload: OrganizeDocumentRequest,
) -> PreparedOrganization:
    document = document_service.get_document_reference(
        db,
        user_id,
        payload.document_id,
    )
    if document is None:
        raise OrganizeNotFoundError("资料不存在")
    if document.status != DocumentStatus.INDEXED.value:
        raise OrganizeConflictError("资料尚未完成索引，暂时不能整理")

    chunks = _document_chunks(db, user_id, [document.id])
    if not chunks:
        raise OrganizeConflictError("资料没有可整理的文本内容")
    context = _context_from_chunks([(document, chunks)])
    return PreparedOrganization(
        context=context,
        source_document_ids=[document.id],
        note_title=f"{document.title} - {payload.mode.value}",
    )


def organize_collection(
    db: Session,
    user_id: UUID,
    payload: OrganizeCollectionRequest,
    llm_provider: LLMProvider | None = None,
) -> OrganizeResponse:
    try:
        prepared = _prepare_collection_organization(db, user_id, payload)
    except Exception:
        db.rollback()
        raise
    db.rollback()
    provider = llm_provider or get_llm_provider()
    result = provider.organize_with_context(payload.mode.value, prepared.context)
    validate_provider_text_length(
        result,
        max_length=ORGANIZE_RESULT_MAX_LENGTH,
        output_name="organization result",
    )

    saved_document_id = None
    if payload.save_as_note:
        saved = _save_result_note(
            db=db,
            user_id=user_id,
            title=prepared.note_title,
            result=result,
            source_document_ids=prepared.source_document_ids,
        )
        saved_document_id = saved.id

    return OrganizeResponse(
        mode=payload.mode.value,
        result=result,
        source_document_ids=prepared.source_document_ids,
        saved_document_id=saved_document_id,
    )


def _prepare_collection_organization(
    db: Session,
    user_id: UUID,
    payload: OrganizeCollectionRequest,
) -> PreparedOrganization:
    document_ids = list(dict.fromkeys(payload.document_ids))
    has_explicit_scope = bool(document_ids) or payload.tag is not None
    if payload.tag:
        tagged_ids = tag_service.document_ids_for_tags(
            db,
            user_id,
            [payload.tag],
            limit=MAX_COLLECTION_DOCUMENTS + 1,
        )
        document_ids = [document_id for document_id in document_ids if document_id in set(tagged_ids)] if document_ids else tagged_ids
    if not document_ids:
        if has_explicit_scope:
            raise OrganizeNotFoundError("所选范围内没有可整理的资料")
        document_ids = list(
            db.scalars(
                select(Document.id)
                .where(Document.user_id == user_id, Document.status == DocumentStatus.INDEXED.value)
                .order_by(Document.created_at.desc(), Document.id.desc())
                .limit(10)
            )
        )

    documents = document_service.list_document_references(
        db,
        user_id,
        document_ids,
        limit=MAX_COLLECTION_DOCUMENTS + 1,
    )
    if not documents:
        raise OrganizeNotFoundError("没有找到可整理的资料")
    if len(documents) > MAX_COLLECTION_DOCUMENTS:
        raise OrganizeValidationError(
            f"一次最多整理 {MAX_COLLECTION_DOCUMENTS} 份资料，请缩小范围"
        )

    per_document_limit = max(
        1,
        min(4, MAX_ORGANIZE_CONTEXT_CHARS // (len(documents) * 1200)),
    )
    chunks_by_id = _collection_chunks(
        db,
        user_id,
        [document.id for document in documents],
        per_document_limit=per_document_limit,
    )
    documents_with_chunks = [
        (document, chunks_by_id.get(document.id, []))
        for document in documents
        if chunks_by_id.get(document.id)
    ]
    context = _context_from_chunks(documents_with_chunks)
    if not context.strip():
        raise OrganizeConflictError("所选资料没有可整理的文本内容")
    source_document_ids = [document.id for document, _ in documents_with_chunks]
    return PreparedOrganization(
        context=context,
        source_document_ids=source_document_ids,
        note_title=f"资料整理 - {payload.mode.value}",
    )


def save_organize_result(
    db: Session,
    user_id: UUID,
    payload: OrganizeResultSaveRequest,
) -> OrganizeResultSaveResponse:
    try:
        source_document_ids = list(dict.fromkeys(payload.source_document_ids))
        owned_ids = set(
            db.scalars(
                select(Document.id).where(
                    Document.user_id == user_id,
                    Document.id.in_(source_document_ids),
                )
            )
        )
        if owned_ids != set(source_document_ids):
            raise OrganizeNotFoundError("来源资料不存在")
    except Exception:
        db.rollback()
        raise
    db.rollback()

    note = _save_result_note(
        db=db,
        user_id=user_id,
        title=payload.title,
        result=payload.result,
        source_document_ids=source_document_ids,
    )
    return OrganizeResultSaveResponse(saved_document_id=note.id)


def _document_chunks(
    db: Session,
    user_id: UUID,
    document_ids: list[UUID],
    limit: int = 20,
) -> list[ContextChunk]:
    return context_chunk_service.load_context_chunks(
        db,
        document_ids,
        user_id=user_id,
        limit=limit,
    )


def _collection_chunks(
    db: Session,
    user_id: UUID,
    document_ids: list[UUID],
    per_document_limit: int,
) -> dict[UUID, list[ContextChunk]]:
    chunks = context_chunk_service.load_partitioned_context_chunks(
        db,
        user_id,
        document_ids,
        per_document_limit=per_document_limit,
    )
    grouped = {document_id: [] for document_id in document_ids}
    for item in chunks:
        grouped[item.document_id].append(item)
    return grouped


def _context_from_chunks(
    documents_with_chunks: list[tuple[Document, list[ContextChunk]]],
    max_chars: int = MAX_ORGANIZE_CONTEXT_CHARS,
) -> str:
    if not documents_with_chunks or max_chars <= 0:
        return ""

    parts: list[str] = []
    index = 1
    remaining_total = max_chars
    per_document_budget = max_chars // len(documents_with_chunks)
    for document, chunks in documents_with_chunks:
        remaining_document = min(per_document_budget, remaining_total)
        for chunk in chunks:
            prefix = (
                f"[资料 {index}]\n标题：{document.title}\n"
                f"位置：片段 {chunk.chunk_index + 1}\n片段："
            )
            separator_length = 2 if parts else 0
            content_budget = remaining_document - len(prefix) - separator_length
            if content_budget <= 0:
                break
            content = chunk.content.strip()
            if len(content) > content_budget:
                content = content[: max(content_budget - 1, 0)] + "…"
            block = prefix + content
            consumed = len(block) + separator_length
            parts.append(block)
            remaining_document -= consumed
            remaining_total -= consumed
            index += 1
            if remaining_document <= 0 or remaining_total <= 0:
                break
        if remaining_total <= 0:
            break
    return "\n\n".join(parts)


def _save_result_note(db: Session, user_id: UUID, title: str, result: str, source_document_ids: list[UUID]) -> Document:
    return document_service.create_note(
        db,
        user_id,
        NoteCreate(
            title=title[:255],
            content=result,
            tags=["AI整理"],
        ),
        source_type=DocumentSourceType.AI_GENERATED,
        metadata={
            "source_document_ids": [
                str(document_id) for document_id in source_document_ids
            ]
        },
    )
