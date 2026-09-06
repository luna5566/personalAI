from __future__ import annotations

from dataclasses import replace
import re
from typing import Sequence, TypeVar
from uuid import UUID

T = TypeVar("T")


def rerank_chunks(query: str, chunks: Sequence[T], top_k: int) -> list[T]:
    if not chunks:
        return []

    terms = _terms(query)
    rescored = [_with_rerank_score(chunk, terms, query) for chunk in chunks]
    candidates = sorted(rescored, key=lambda item: getattr(item, "score"), reverse=True)

    selected: list[T] = []
    document_counts: dict[UUID, int] = {}
    while candidates and len(selected) < top_k:
        best_index = max(
            range(len(candidates)),
            key=lambda index: _diversified_score(candidates[index], document_counts),
        )
        item = candidates.pop(best_index)
        selected.append(item)
        document_id = getattr(item, "document_id")
        document_counts[document_id] = document_counts.get(document_id, 0) + 1

    return selected


def _with_rerank_score(chunk: T, terms: list[str], query: str) -> T:
    base_score = float(getattr(chunk, "score"))
    text = _chunk_text(chunk)
    title = str(getattr(chunk, "document_title", "")).lower()

    coverage = _coverage_score(terms, text)
    title_coverage = _coverage_score(terms, title)
    phrase_bonus = 0.08 if query.strip().lower() and query.strip().lower() in text else 0.0
    section_bonus = 0.03 if getattr(chunk, "section_title", None) else 0.0

    score = base_score * 0.72 + coverage * 0.18 + title_coverage * 0.07 + phrase_bonus + section_bonus
    return replace(chunk, score=min(score, 1.0))


def _diversified_score(chunk: T, document_counts: dict[UUID, int]) -> float:
    document_id = getattr(chunk, "document_id")
    crowding_penalty = min(document_counts.get(document_id, 0), 3) * 0.035
    return float(getattr(chunk, "score")) - crowding_penalty


def _coverage_score(terms: list[str], text: str) -> float:
    if not terms or not text:
        return 0.0
    matched = sum(1 for term in terms if term in text)
    return matched / len(terms)


def _chunk_text(chunk: T) -> str:
    values = [
        getattr(chunk, "document_title", ""),
        getattr(chunk, "section_title", "") or "",
        getattr(chunk, "content", ""),
    ]
    return " ".join(str(value).lower() for value in values if value)


def _terms(query: str) -> list[str]:
    raw_terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_+#.-]{2,}", query)
    terms: list[str] = []
    seen: set[str] = set()

    for raw_term in raw_terms:
        candidates = [raw_term]
        if _is_cjk_text(raw_term) and len(raw_term) > 6:
            candidates.extend(raw_term[index : index + 4] for index in range(0, len(raw_term) - 3, 2))

        for candidate in candidates:
            term = candidate.strip().lower()
            if len(term) < 2 or term in seen:
                continue
            seen.add(term)
            terms.append(term)
            if len(terms) >= 12:
                return terms

    return terms


def _is_cjk_text(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)
