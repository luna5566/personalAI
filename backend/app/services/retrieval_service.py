from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import re
from uuid import UUID

from sqlalchemy import Select, exists, func, literal, or_, select, union
from sqlalchemy.orm import Session

from app.ai.embedding_provider import EmbeddingProvider, get_embedding_provider
from app.ai.rerank_provider import get_rerank_provider
from app.core.config import settings
from app.core.database import set_local_hnsw_search_options
from app.core.request_limits import (
    CHAT_SCOPE_DOCUMENT_LIMIT,
    CHAT_SCOPE_SOURCE_TYPE_LIMIT,
    RETRIEVAL_CHUNK_CONTENT_MAX_LENGTH,
)
from app.models.chunk import DocumentChunk, chunk_search_text_expression
from app.models.document import Document
from app.models.embedding import ChunkEmbedding
from app.models.tag import DocumentTag, Tag
from app.rag.reranker import rerank_chunks
from app.services import tag_service
from app.utils.sql import escape_like_pattern


MIN_RETRIEVAL_SCORE = 0.35


class RetrievalScopeValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    source_type: str
    chunk_index: int
    content: str
    start_offset: int
    end_offset: int
    score: float
    page_number: int | None = None
    section_title: str | None = None


def vector_search(
    db: Session,
    user_id: UUID,
    query: str,
    top_k: int = 8,
    document_ids: list[UUID] | None = None,
    exclude_document_ids: list[UUID] | None = None,
    tag_names: list[str] | None = None,
    source_types: list[str] | None = None,
    created_after: datetime | None = None,
    provider: EmbeddingProvider | None = None,
) -> list[RetrievedChunk]:
    tag_names = _validate_scope_filter_sizes(
        document_ids=document_ids,
        tag_names=tag_names,
        source_types=source_types,
    )
    if document_ids is not None and not document_ids:
        return []

    provider = provider or get_embedding_provider()
    query_vector = provider.embed_texts([query])[0]
    set_local_hnsw_search_options(
        db,
        ef_search=settings.hnsw_ef_search,
        max_scan_tuples=settings.hnsw_max_scan_tuples,
    )
    distance = ChunkEmbedding.embedding.l2_distance(query_vector).label("distance")

    stmt = (
        select(*_retrieval_result_columns(), distance)
        .select_from(DocumentChunk)
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.user_id == user_id)
        .where(ChunkEmbedding.embedding_model == provider.index_id)
        .where(ChunkEmbedding.embedding_dimensions == provider.dimensions)
        .order_by(distance.asc())
        .limit(top_k)
    )
    stmt = _apply_scope_filters(
        stmt,
        user_id=user_id,
        document_ids=document_ids,
        tag_names=tag_names,
        source_types=source_types,
        created_after=created_after,
    )
    if exclude_document_ids:
        stmt = stmt.where(DocumentChunk.document_id.notin_(exclude_document_ids))

    vector_results: list[RetrievedChunk] = []
    for row in db.execute(stmt):
        distance_value = float(row.distance)
        vector_results.append(
            _retrieved_chunk_from_row(
                row,
                score=1.0 / (1.0 + distance_value),
            )
        )

    keyword_results = keyword_search(
        db=db,
        user_id=user_id,
        query=query,
        top_k=top_k,
        document_ids=document_ids,
        exclude_document_ids=exclude_document_ids,
        tag_names=tag_names,
        source_types=source_types,
        created_after=created_after,
    )
    merged_results = _merge_results(vector_results, keyword_results)
    model_reranked = _apply_model_rerank(query, merged_results, top_k)
    if model_reranked is not None:
        reranked = model_reranked
    else:
        reranked = rerank_chunks(query, merged_results, top_k)
    return _filter_relevant_chunks(reranked)


def _apply_model_rerank(
    query: str,
    chunks: list[RetrievedChunk],
    top_k: int,
) -> list[RetrievedChunk] | None:
    """模型重排可用时返回按 relevance score 排序的 top_k，否则返回 None 走启发式重排。"""
    if settings.rerank_provider == "disabled" or not chunks:
        return None
    try:
        provider = get_rerank_provider()
        scores = provider.rerank(
            query,
            [chunk.content for chunk in chunks],
            top_n=min(top_k * 2, len(chunks)),
        )
    except Exception:
        # 模型重排失败时退回启发式重排，不影响问答可用性。
        return None
    rescored = [
        replace(chunk, score=scores[index])
        for index, chunk in enumerate(chunks)
        if index < len(scores)
    ]
    rescored.sort(key=lambda item: item.score, reverse=True)
    return rescored[:top_k]


def keyword_search(
    db: Session,
    user_id: UUID,
    query: str,
    top_k: int = 8,
    document_ids: list[UUID] | None = None,
    exclude_document_ids: list[UUID] | None = None,
    tag_names: list[str] | None = None,
    source_types: list[str] | None = None,
    created_after: datetime | None = None,
) -> list[RetrievedChunk]:
    tag_names = _validate_scope_filter_sizes(
        document_ids=document_ids,
        tag_names=tag_names,
        source_types=source_types,
    )
    if document_ids is not None and not document_ids:
        return []

    terms = _keyword_terms(query)
    if not terms:
        return []

    title_filters = []
    chunk_filters = []
    chunk_prefilters = []
    for term in terms:
        pattern = f"%{escape_like_pattern(term)}%"
        title_filters.append(
            Document.title.ilike(pattern, escape="\\")
        )
        chunk_filters.extend(
            (
                DocumentChunk.content.ilike(pattern, escape="\\"),
                DocumentChunk.section_title.ilike(pattern, escape="\\"),
            )
        )
        chunk_prefilters.append(
            chunk_search_text_expression().ilike(pattern, escape="\\")
        )

    candidate_chunks = union(
        select(DocumentChunk.id.label("chunk_id")).where(
            DocumentChunk.user_id == user_id,
            or_(*chunk_prefilters),
        ),
        select(DocumentChunk.id.label("chunk_id"))
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.user_id == user_id,
            Document.user_id == user_id,
            or_(*title_filters),
        ),
    ).cte("keyword_candidate_chunks")
    keyword_score = _keyword_score_expression(terms)
    stmt = (
        select(*_retrieval_result_columns())
        .select_from(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(
            candidate_chunks,
            candidate_chunks.c.chunk_id == DocumentChunk.id,
        )
        .where(DocumentChunk.user_id == user_id)
        .where(or_(*title_filters, *chunk_filters))
        .order_by(keyword_score.desc(), DocumentChunk.id)
        .limit(max(top_k * 6, 24))
    )
    stmt = _apply_scope_filters(
        stmt,
        user_id=user_id,
        document_ids=document_ids,
        tag_names=tag_names,
        source_types=source_types,
        created_after=created_after,
    )
    if exclude_document_ids:
        stmt = stmt.where(DocumentChunk.document_id.notin_(exclude_document_ids))

    ranked: list[RetrievedChunk] = []
    for row in db.execute(stmt):
        score = _keyword_score(
            query_terms=terms,
            chunk_content=row.content,
            section_title=row.section_title,
            document_title=row.document_title,
        )
        ranked.append(
            _retrieved_chunk_from_row(row, score=score)
        )

    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked[:top_k]


def created_after_from_recent_days(recent_days: int | None) -> datetime | None:
    if recent_days is None:
        return None
    if recent_days < 1:
        return None
    return datetime.now(timezone.utc) - timedelta(days=recent_days)


def _apply_scope_filters(
    stmt: Select,
    *,
    user_id: UUID,
    document_ids: list[UUID] | None,
    tag_names: list[str] | None,
    source_types: list[str] | None,
    created_after: datetime | None = None,
) -> Select:
    if document_ids is not None:
        stmt = stmt.where(DocumentChunk.document_id.in_(document_ids))
    if tag_names:
        tag_match = (
            select(1)
            .select_from(DocumentTag)
            .join(Tag, Tag.id == DocumentTag.tag_id)
            .where(
                DocumentTag.document_id == Document.id,
                Tag.user_id == user_id,
                Tag.name.in_(tag_names),
            )
        )
        stmt = stmt.where(exists(tag_match))
    if source_types:
        stmt = stmt.where(Document.source_type.in_(source_types))
    if created_after is not None:
        stmt = stmt.where(Document.created_at >= created_after)
    return stmt


def _validate_scope_filter_sizes(
    *,
    document_ids: list[UUID] | None,
    tag_names: list[str] | None,
    source_types: list[str] | None,
) -> list[str] | None:
    if document_ids is not None and len(document_ids) > CHAT_SCOPE_DOCUMENT_LIMIT:
        raise RetrievalScopeValidationError(
            f"聊天范围最多包含 {CHAT_SCOPE_DOCUMENT_LIMIT} 份资料"
        )
    normalized_tags = (
        tag_service.normalize_document_tag_names(tag_names)
        if tag_names
        else None
    )
    if source_types is not None and len(source_types) > CHAT_SCOPE_SOURCE_TYPE_LIMIT:
        raise RetrievalScopeValidationError(
            f"聊天范围最多包含 {CHAT_SCOPE_SOURCE_TYPE_LIMIT} 种资料来源"
        )
    return normalized_tags


def _merge_results(
    vector_results: list[RetrievedChunk],
    keyword_results: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    merged: dict[UUID, RetrievedChunk] = {item.chunk_id: item for item in vector_results}
    for keyword_item in keyword_results:
        existing = merged.get(keyword_item.chunk_id)
        if existing is None:
            merged[keyword_item.chunk_id] = keyword_item
            continue
        merged[keyword_item.chunk_id] = RetrievedChunk(
            chunk_id=existing.chunk_id,
            document_id=existing.document_id,
            document_title=existing.document_title,
            source_type=existing.source_type,
            chunk_index=existing.chunk_index,
            content=existing.content,
            start_offset=existing.start_offset,
            end_offset=existing.end_offset,
            score=max(existing.score, min(existing.score + keyword_item.score * 0.2, 1.0)),
            page_number=existing.page_number,
            section_title=existing.section_title,
        )
    return sorted(merged.values(), key=lambda item: item.score, reverse=True)


def _keyword_terms(query: str) -> list[str]:
    raw_terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_+#.-]{2,}", query)
    terms: list[str] = []
    seen: set[str] = set()
    for raw_term in raw_terms:
        candidates = [raw_term]
        if _is_cjk_text(raw_term) and len(raw_term) > 6:
            candidates.extend(raw_term[index : index + 4] for index in range(0, len(raw_term) - 3, 2))
        for candidate in candidates:
            normalized = candidate.strip().lower()
            if len(normalized) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(normalized)
            if len(terms) >= 10:
                return terms
    return terms


def _retrieval_result_columns() -> tuple:
    content = func.left(
        DocumentChunk.content,
        RETRIEVAL_CHUNK_CONTENT_MAX_LENGTH,
    ).label("content")
    bounded_end_offset = func.least(
        DocumentChunk.end_offset,
        DocumentChunk.start_offset + func.char_length(content),
    ).label("end_offset")
    return (
        DocumentChunk.id.label("chunk_id"),
        DocumentChunk.document_id.label("document_id"),
        Document.title.label("document_title"),
        Document.source_type.label("source_type"),
        DocumentChunk.chunk_index.label("chunk_index"),
        content,
        DocumentChunk.start_offset.label("start_offset"),
        bounded_end_offset,
        DocumentChunk.page_number.label("page_number"),
        DocumentChunk.section_title.label("section_title"),
    )


def _retrieved_chunk_from_row(row, *, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        document_title=row.document_title,
        source_type=row.source_type,
        chunk_index=row.chunk_index,
        content=row.content,
        start_offset=row.start_offset,
        end_offset=row.end_offset,
        score=score,
        page_number=row.page_number,
        section_title=row.section_title,
    )


def _keyword_score(
    query_terms: list[str],
    *,
    chunk_content: str,
    section_title: str | None,
    document_title: str,
) -> float:
    haystack = " ".join(
        value.lower()
        for value in [document_title, section_title or "", chunk_content]
        if value
    )
    if not haystack:
        return 0.0

    matches = sum(haystack.count(term) for term in query_terms)
    title_matches = sum(document_title.lower().count(term) for term in query_terms)
    score = 0.55 + min(matches, 6) * 0.05 + min(title_matches, 3) * 0.06
    return min(score, 0.92)


def _keyword_score_expression(query_terms: list[str]):
    haystack = func.lower(
        func.coalesce(Document.title, "")
        + literal(" ")
        + func.coalesce(DocumentChunk.section_title, "")
        + literal(" ")
        + DocumentChunk.content
    )
    title = func.lower(Document.title)
    matches = sum(
        (_term_occurrence_count(haystack, term) for term in query_terms),
        literal(0),
    )
    title_matches = sum(
        (_term_occurrence_count(title, term) for term in query_terms),
        literal(0),
    )
    return (
        literal(0.55)
        + func.least(matches, 6) * 0.05
        + func.least(title_matches, 3) * 0.06
    )


def _term_occurrence_count(value, term: str):
    return (
        func.char_length(value)
        - func.char_length(func.replace(value, term, ""))
    ) / len(term)


def _is_cjk_text(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _filter_relevant_chunks(
    chunks: list[RetrievedChunk],
    min_score: float = MIN_RETRIEVAL_SCORE,
) -> list[RetrievedChunk]:
    return [chunk for chunk in chunks if chunk.score >= min_score]
