from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from typing import TypeVar
from uuid import UUID

T = TypeVar("T")

# MMR 多样性权重：1.0 时与相关度等权；经验值 0.4 在抑制冗余与保留相关度间平衡
MMR_LAMBDA_DEFAULT = 0.4


def rerank_chunks(
    query: str,
    chunks: Sequence[T],
    top_k: int,
    *,
    mmr_lambda: float | None = None,
) -> list[T]:
    if not chunks:
        return []

    terms = _terms(query)
    rescored = [_with_rerank_score(chunk, terms, query) for chunk in chunks]
    candidates = sorted(rescored, key=lambda item: item.score, reverse=True)
    return select_diverse(candidates, top_k, mmr_lambda=mmr_lambda)


def select_diverse(
    chunks: Sequence[T],
    top_k: int,
    *,
    mmr_lambda: float | None = None,
) -> list[T]:
    """按已排序的相关度做 MMR 多样性选择。

    输入应已按相关度降序排列；逐步选出「相关度 - 冗余惩罚」最高的候选，
    抑制同一文档相邻/重叠片段霸占整个上下文。`mmr_lambda=0` 退化为纯
    相关度截断。
    """
    selected: list[T] = []
    document_counts: dict[UUID, int] = {}
    candidates = list(chunks)
    while candidates and len(selected) < top_k:
        best_index = max(
            range(len(candidates)),
            key=lambda index: _diversified_score(
                candidates[index], document_counts, selected, mmr_lambda
            ),
        )
        item = candidates.pop(best_index)
        selected.append(item)
        document_id = item.document_id
        document_counts[document_id] = document_counts.get(document_id, 0) + 1
    return selected


def _with_rerank_score(chunk: T, terms: list[str], query: str) -> T:
    base_score = float(chunk.score)
    text = _chunk_text(chunk)
    title = str(getattr(chunk, "document_title", "")).lower()

    coverage = _coverage_score(terms, text)
    title_coverage = _coverage_score(terms, title)
    phrase_bonus = 0.08 if query.strip().lower() and query.strip().lower() in text else 0.0
    section_bonus = 0.03 if getattr(chunk, "section_title", None) else 0.0

    score = base_score * 0.72 + coverage * 0.18 + title_coverage * 0.07 + phrase_bonus + section_bonus
    return replace(chunk, score=min(score, 1.0))


def _diversified_score(
    chunk: T,
    document_counts: dict[UUID, int],
    selected: Sequence[T],
    mmr_lambda: float | None,
) -> float:
    document_id = chunk.document_id
    crowding_penalty = min(document_counts.get(document_id, 0), 3) * 0.035
    similarity = _max_similarity_to_selected(chunk, selected)
    if similarity <= 0.0:
        return float(chunk.score) - crowding_penalty
    # MMR：相关度扣减与已选内容的最大词面相似度，抑制相邻/重叠片段重复入选
    effective_lambda = (
        MMR_LAMBDA_DEFAULT if mmr_lambda is None else mmr_lambda
    )
    return float(chunk.score) - crowding_penalty - effective_lambda * similarity


def _max_similarity_to_selected(chunk: T, selected: Sequence[T]) -> float:
    if not selected:
        return 0.0
    text = _chunk_text(chunk)
    if not text:
        return 0.0
    chunk_tokens = set(_tokenize(text))
    if not chunk_tokens:
        return 0.0
    best = 0.0
    for chosen in selected:
        chosen_tokens = set(_tokenize(_chunk_text(chosen)))
        if not chosen_tokens:
            continue
        overlap = len(chunk_tokens & chosen_tokens)
        similarity = overlap / len(chunk_tokens | chosen_tokens)
        if similarity > best:
            best = similarity
    return best


def _tokenize(text: str) -> set[str]:
    """字符级 3-gram：对中文长句切块的内容重叠度量稳定（词级切分对
    无分词文本会退化成超长 token，Jaccard 失真）。"""
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 3:
        return {compact} if compact else set()
    return {compact[index : index + 3] for index in range(len(compact) - 2)}


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
