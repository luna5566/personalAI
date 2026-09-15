"""大知识库检索延迟基准：生成合成语料入库，测量 vector_search 端到端延迟。

在真实 PostgreSQL + pgvector 上运行（需已完成 alembic upgrade head 并创建
默认用户）。语料使用 local_hash 离线 embedding，无需外部 API Key；向量
维度与生产一致，HNSW 索引行为与真实部署相同，适合评估索引参数与硬件
吞吐，不适合评估语义检索质量（质量用 eval_retrieval.py）。

用法（在 backend 目录）：

    python scripts/bench_retrieval.py                          # 约 2000 chunk
    python scripts/bench_retrieval.py --documents 2000 --queries 100
    python scripts/bench_retrieval.py --ef-search 40           # 对比 HNSW 参数
    python scripts/bench_retrieval.py --json

输出每查询延迟的 P50/P90/P99（毫秒）。基准结束后自动删除合成语料。
"""

import argparse
import json
import statistics
import sys
import time
from uuid import uuid4

sys.path.append(str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.models.embedding import ChunkEmbedding
from app.services import chunking_service, embedding_service

DEFAULT_DOCUMENTS = 500
DEFAULT_CHUNKS_PER_DOCUMENT = 4
DEFAULT_QUERIES = 50

_PARAGRAPH_SENTENCES = (
    "本文讨论{}在系统中的核心作用，并给出可操作的配置建议。",
    "实际部署时需要关注{}的容量上限与失效恢复策略。",
    "围绕{}的常见误区包括忽略基线开销和低估长尾延迟。",
    "通过分层缓存可以显著缓解{}带来的压力，同时保持一致性约束。",
    "监控指标应当覆盖{}的关键路径，并在阈值突破时触发告警。",
    "团队复盘发现{}相关的故障多集中在变更窗口内。",
)
_TOPIC_WORDS = (
    "检索", "索引", "缓存", "分片", "限流", "回滚", "幂等", "租约",
    "心跳", "批处理", "降级", "预热", "抖动", "扩容", "压缩", "校验",
)


def _document_text(index: int, paragraphs: int) -> str:
    parts = [f"基准语料文档{index}（主题：{_TOPIC_WORDS[index % len(_TOPIC_WORDS)]}）"]
    for p in range(paragraphs):
        template = _PARAGRAPH_SENTENCES[(index + p) % len(_PARAGRAPH_SENTENCES)]
        topic = _TOPIC_WORDS[(index * 3 + p) % len(_TOPIC_WORDS)]
        parts.append(template.format(topic) * 3)
    return "\n\n".join(parts)


def _seed_corpus(db, user_id, documents: int, paragraphs: int) -> list:
    created: list[Document] = []
    try:
        for index in range(documents):
            document = Document(
                id=uuid4(),
                user_id=user_id,
                title=f"基准语料文档{index}",
                source_type="note",
                raw_text="",
                cleaned_text=_document_text(index, paragraphs),
                status=DocumentStatus.INDEXED.value,
                metadata_={"bench_seed": True},
            )
            chunks = chunking_service.build_document_chunks(document)
            embeddings = embedding_service.generate_chunk_embeddings(chunks)
            db.add(document)
            db.add_all(chunks)
            db.add_all(embeddings)
            created.append(document)
            if len(created) % 50 == 0:
                db.commit()
        db.commit()
    except Exception:
        db.rollback()
        _drop_corpus(db, [doc.id for doc in created])
        raise
    return created


def _drop_corpus(db, document_ids) -> None:
    if not document_ids:
        return
    db.execute(
        delete(ChunkEmbedding).where(ChunkEmbedding.document_id.in_(document_ids))
    )
    db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id.in_(document_ids))
    )
    db.execute(delete(Document).where(Document.id.in_(document_ids)))
    db.commit()


def _count_chunks(db, user_id) -> int:
    return db.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.user_id == user_id)
    ) or 0


def _sample_queries(db, user_id, count: int) -> list[str]:
    rows = db.execute(
        select(DocumentChunk.content)
        .where(DocumentChunk.user_id == user_id)
        .order_by(DocumentChunk.id)
        .limit(200)
    ).scalars()
    pool = [row[:40] for row in rows if row]
    if not pool:
        raise RuntimeError("语料为空，无法生成查询")
    return [pool[i % len(pool)] for i in range(count)]


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(
        len(sorted_values) - 1,
        max(0, round(pct / 100 * (len(sorted_values) - 1))),
    )
    return sorted_values[index]


def main() -> int:
    parser = argparse.ArgumentParser(description="检索延迟基准")
    parser.add_argument("--documents", type=int, default=DEFAULT_DOCUMENTS)
    parser.add_argument(
        "--chunks-per-doc",
        type=int,
        default=DEFAULT_CHUNKS_PER_DOCUMENT,
        help="每篇文档的段落数（切块后 chunk 数量与之接近）",
    )
    parser.add_argument("--queries", type=int, default=DEFAULT_QUERIES)
    parser.add_argument(
        "--ef-search",
        type=int,
        default=None,
        help="临时覆盖 hnsw_ef_search（默认用 .env 配置）",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.ef_search is not None:
        settings.hnsw_ef_search = args.ef_search

    user_id = settings.default_user_id

    # 预先清理上次异常退出遗留的基准语料
    with SessionLocal() as db:
        stale = db.scalars(
            select(Document.id).where(
                Document.user_id == user_id,
                Document.title.like("基准语料文档%"),
            )
        ).all()
        _drop_corpus(db, list(stale))

    print(
        f"播种 {args.documents} 篇语料（每篇 {args.chunks_per_doc} 段落）...",
        flush=True,
    )
    started = time.perf_counter()
    with SessionLocal() as db:
        created = _seed_corpus(
            db,
            user_id,
            args.documents,
            args.chunks_per_doc,
        )
        chunk_count = _count_chunks(db, user_id)
    seed_seconds = time.perf_counter() - started
    print(f"语料就绪：{len(created)} 篇 / {chunk_count} chunk，{seed_seconds:.1f}s")

    print(f"执行 {args.queries} 次检索...", flush=True)
    latencies_ms: list[float] = []
    with SessionLocal() as db:
        queries = _sample_queries(db, user_id, args.queries)
        for query in queries:
            started = time.perf_counter()
            retrieval_service_bench(query, user_id, db)
            latencies_ms.append((time.perf_counter() - started) * 1000)

    with SessionLocal() as cleanup_db:
        _drop_corpus(cleanup_db, [doc.id for doc in created])
    print("基准语料已清理")

    latencies_ms.sort()
    summary = {
        "chunks": chunk_count,
        "documents": len(created),
        "queries": args.queries,
        "hnsw_ef_search": settings.hnsw_ef_search,
        "hnsw_max_scan_tuples": settings.hnsw_max_scan_tuples,
        "p50_ms": round(_percentile(latencies_ms, 50), 1),
        "p90_ms": round(_percentile(latencies_ms, 90), 1),
        "p99_ms": round(_percentile(latencies_ms, 99), 1),
        "mean_ms": round(statistics.fmean(latencies_ms), 1),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"chunk={summary['chunks']}  ef_search={summary['hnsw_ef_search']}"
        )
        print(
            f"P50={summary['p50_ms']}ms  P90={summary['p90_ms']}ms  "
            f"P99={summary['p99_ms']}ms  mean={summary['mean_ms']}ms"
        )
    return 0


def retrieval_service_bench(query: str, user_id, db):
    from app.services import retrieval_service

    return retrieval_service.vector_search(db=db, user_id=user_id, query=query)


if __name__ == "__main__":
    raise SystemExit(main())
