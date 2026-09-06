from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.llm_provider import LLMProvider, get_llm_provider
from app.ai.output_validation import validate_provider_text_length
from app.core.request_limits import (
    DOCUMENT_SUMMARY_MAX_LENGTH,
    DOCUMENT_TAG_LIMIT,
    ENRICHMENT_TAG_OUTPUT_MAX_LENGTH,
    RAG_CONTEXT_MAX_LENGTH,
)
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.services import context_chunk_service, tag_service
from app.services.context_chunk_service import ContextChunk
from app.services.job_error_service import (
    PublicJobError,
    public_job_error_message,
)

AUTO_TAG_LIMIT = 5
ENRICHMENT_CHUNK_LIMIT = 8


logger = logging.getLogger(__name__)


class EnrichmentProviderError(PublicJobError):
    pass


@dataclass(frozen=True)
class GeneratedEnrichment:
    summary: str | None
    tags: list[str]


def load_document_enrichment_chunks(
    db: Session,
    document_id: UUID,
) -> list[ContextChunk]:
    return context_chunk_service.load_context_chunks(
        db,
        [document_id],
        limit=ENRICHMENT_CHUNK_LIMIT,
    )


def enrich_document(
    db: Session,
    document: Document,
    chunks: list[DocumentChunk] | list[ContextChunk],
    provider: LLMProvider | None = None,
) -> list[str]:
    generated = generate_document_enrichment(
        document,
        chunks,
        provider=provider,
    )
    existing_tags = tag_service.document_tag_names(db, document.id)
    merged_tags, applied_auto_tags = apply_generated_enrichment(
        document,
        generated,
        existing_tags=existing_tags,
    )
    tag_service.set_document_tags(db, document.user_id, document.id, merged_tags)
    db.add(document)
    return applied_auto_tags


def generate_document_enrichment(
    document: Document,
    chunks: list[DocumentChunk] | list[ContextChunk],
    provider: LLMProvider | None = None,
) -> GeneratedEnrichment:
    context = _build_context(document, chunks)
    if not context:
        raise EnrichmentProviderError("资料没有可用于摘要的文本内容")

    provider = provider or get_llm_provider()
    try:
        summary = validate_provider_text_length(
            provider.organize_with_context("summary", context),
            max_length=DOCUMENT_SUMMARY_MAX_LENGTH,
            output_name="document summary",
        ).strip()
        tag_output = validate_provider_text_length(
            provider.organize_with_context("tags", context),
            max_length=ENRICHMENT_TAG_OUTPUT_MAX_LENGTH,
            output_name="document tag output",
        ).strip()
    except Exception as exc:
        logger.warning("Document enrichment provider failed", exc_info=True)
        raise EnrichmentProviderError(
            "资料摘要和标签生成失败，请检查模型配置后重试"
        ) from exc

    return GeneratedEnrichment(
        summary=summary or None,
        tags=_parse_generated_tags(tag_output),
    )


def apply_generated_enrichment(
    document: Document,
    generated: GeneratedEnrichment,
    *,
    existing_tags: list[str],
) -> tuple[list[str], list[str]]:
    retained_tags = list(dict.fromkeys(existing_tags))[:DOCUMENT_TAG_LIMIT]
    applied_auto_tags = [
        tag for tag in generated.tags if tag not in retained_tags
    ][: max(DOCUMENT_TAG_LIMIT - len(retained_tags), 0)]
    merged_tags = [*retained_tags, *applied_auto_tags]

    document.summary = generated.summary
    metadata = dict(document.metadata_ or {})
    metadata["auto_tags"] = applied_auto_tags
    metadata.pop("enrichment_error", None)
    document.metadata_ = metadata
    return merged_tags, applied_auto_tags


def record_enrichment_error(document: Document, error: Exception) -> None:
    metadata = dict(document.metadata_ or {})
    metadata["enrichment_error"] = public_job_error_message(
        error,
        "资料摘要和标签生成失败，请检查模型配置后重试",
    )
    document.metadata_ = metadata


def _build_context(
    document: Document,
    chunks: list[DocumentChunk] | list[ContextChunk],
    max_chars: int = RAG_CONTEXT_MAX_LENGTH,
) -> str:
    if max_chars <= 0:
        return ""
    parts: list[str] = []
    used = 0
    for index, chunk in enumerate(
        chunks[:ENRICHMENT_CHUNK_LIMIT],
        start=1,
    ):
        block = (
            f"[资料 {index}]\n"
            f"标题：{document.title}\n"
            f"位置：片段 {chunk.chunk_index + 1}\n"
            f"片段：{chunk.content.strip()}"
        )
        separator_length = 2 if parts else 0
        remaining = max_chars - used - separator_length
        if remaining <= 0:
            break
        if len(block) > remaining:
            if parts:
                break
            block = block[:remaining]
        parts.append(block)
        used += separator_length + len(block)
    return "\n\n".join(parts)


def _parse_generated_tags(value: str) -> list[str]:
    cleaned = value.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    candidates: list[str] = []

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        raw_tags = parsed.get("tags", [])
        if isinstance(raw_tags, list):
            candidates.extend(str(item) for item in raw_tags)
    elif isinstance(parsed, list):
        candidates.extend(str(item) for item in parsed)

    if not candidates:
        cleaned = re.sub(r"^(标签|关键词|tags?)\s*[:：]\s*", "", cleaned, flags=re.IGNORECASE)
        candidates.extend(re.split(r"[,，、;；\n]+", cleaned))

    tags: list[str] = []
    for candidate in candidates:
        tag = re.sub(r"^[\s\-*#\d.]+|[\s。.!！?？]+$", "", candidate).strip()
        if not tag or len(tag) > 20 or tag in tags:
            continue
        tags.append(tag)
        if len(tags) >= AUTO_TAG_LIMIT:
            break
    return tags
