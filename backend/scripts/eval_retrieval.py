"""检索质量评测：基于评测集运行向量混合检索，计算 recall@k 与 MRR。

评测集为 JSONL 文件，每行一个用例：

    {"question": "……", "expected_document_ids": ["<资料 UUID>"]}
    {"question": "……", "expected_keywords": ["关键词1", "关键词2"]}

命中判定：任一返回切片来自 expected_document_ids 之一，或其正文包含
任一 expected_keywords（大小写不敏感的子串匹配）。两类期望都不提供的
用例会被跳过；期望资料在数据库中不存在的用例也会跳过，避免示例数据污染指标。

用法（在 backend 目录、已配置 .env 并完成 alembic upgrade head 后）：

    python scripts/eval_retrieval.py --top-k 8
    python scripts/eval_retrieval.py --min-recall 0.8
    python scripts/eval_retrieval.py --json

换 embedding 模型或调整切片策略前后各跑一次，对比 recall@k 与 MRR。
"""

import argparse
import json
import statistics
import sys
from pathlib import Path
from uuid import UUID

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document
from app.services import retrieval_service
from app.services.retrieval_service import RetrievedChunk

DEFAULT_EVAL_SET = Path(__file__).with_name("retrieval_eval_set.example.jsonl")


def chunk_is_relevant(
    chunk: RetrievedChunk,
    expected_document_ids: frozenset[str],
    expected_keywords: tuple[str, ...],
) -> bool:
    if str(chunk.document_id) in expected_document_ids:
        return True
    content = chunk.content.casefold()
    return any(keyword.casefold() in content for keyword in expected_keywords)


def relevant_ranks(
    retrieved: list[RetrievedChunk],
    expected_document_ids: frozenset[str],
    expected_keywords: tuple[str, ...],
) -> list[int]:
    """返回命中切片的 1-based 排名列表。"""
    return [
        index
        for index, chunk in enumerate(retrieved, start=1)
        if chunk_is_relevant(chunk, expected_document_ids, expected_keywords)
    ]


def summarize(case_results: list[dict]) -> dict:
    evaluated = [case for case in case_results if case["status"] == "evaluated"]
    recall_values = [1.0 if case["ranks"] else 0.0 for case in evaluated]
    mrr_values = [1.0 / case["ranks"][0] if case["ranks"] else 0.0 for case in evaluated]
    return {
        "total_cases": len(case_results),
        "evaluated_cases": len(evaluated),
        "skipped_cases": len(case_results) - len(evaluated),
        "recall_at_k": round(statistics.mean(recall_values), 4) if recall_values else None,
        "mrr": round(statistics.mean(mrr_values), 4) if mrr_values else None,
        "hits": sum(1 for value in recall_values if value > 0),
    }


def load_eval_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            case = json.loads(line)
            if not isinstance(case.get("question"), str) or not case["question"].strip():
                raise ValueError(f"评测集第 {line_number} 行缺少 question")
            cases.append(case)
    return cases


def existing_document_ids(db, user_id: UUID, expected: set[str]) -> set[str]:
    if not expected:
        return set()
    parsed: list[UUID] = []
    for value in expected:
        try:
            parsed.append(UUID(value))
        except ValueError:
            continue
    rows = db.execute(
        select(Document.id).where(Document.user_id == user_id, Document.id.in_(parsed))
    ).scalars()
    return {str(row) for row in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="评测检索质量（recall@k / MRR）")
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=DEFAULT_EVAL_SET,
        help=f"评测集 JSONL 路径（默认 {DEFAULT_EVAL_SET.name}）",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=settings.chat_retrieval_top_k,
        help=f"每次检索返回的切片数（默认 {settings.chat_retrieval_top_k}）",
    )
    parser.add_argument(
        "--user-id",
        type=UUID,
        default=settings.default_user_id,
        help="评测用户的 ID（默认 DEFAULT_USER_ID）",
    )
    parser.add_argument(
        "--min-recall",
        type=float,
        default=None,
        help="recall@k 低于该值时以非零退出码失败（用于门禁）",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args()

    cases = load_eval_cases(args.eval_set)
    case_results: list[dict] = []
    with SessionLocal() as db:
        for case in cases:
            document_ids = {str(value) for value in case.get("expected_document_ids") or []}
            keywords = tuple(case.get("expected_keywords") or ())
            if not document_ids and not keywords:
                case_results.append(
                    {
                        "question": case["question"],
                        "status": "skipped",
                        "reason": "未提供 expected_document_ids 或 expected_keywords",
                        "ranks": [],
                    }
                )
                continue
            missing = document_ids - existing_document_ids(db, args.user_id, document_ids)
            if document_ids and not (document_ids - missing):
                case_results.append(
                    {
                        "question": case["question"],
                        "status": "skipped",
                        "reason": f"期望资料不存在于数据库：{sorted(missing)}",
                        "ranks": [],
                    }
                )
                continue
            retrieved = retrieval_service.vector_search(
                db=db,
                user_id=args.user_id,
                query=case["question"],
                top_k=args.top_k,
            )
            ranks = relevant_ranks(retrieved, frozenset(document_ids), keywords)
            case_results.append(
                {
                    "question": case["question"],
                    "status": "evaluated",
                    "ranks": ranks,
                    "top_titles": [chunk.document_title for chunk in retrieved[:3]],
                }
            )

    summary = summarize(case_results)
    summary["top_k"] = args.top_k
    summary["eval_set"] = str(args.eval_set)

    if args.json:
        print(json.dumps({"summary": summary, "cases": case_results}, ensure_ascii=False, indent=2))
    else:
        print(f"评测集：{args.eval_set}  top_k={args.top_k}")
        for case in case_results:
            if case["status"] == "skipped":
                print(f"  [跳过] {case['question']} —— {case['reason']}")
                continue
            mark = "命中" if case["ranks"] else "未命中"
            first = f"首个命中排名 {case['ranks'][0]}" if case["ranks"] else ""
            titles = "、".join(case["top_titles"])
            print(f"  [{mark}] {case['question']}  {first}  Top3: {titles}")
        recall = summary["recall_at_k"]
        print(
            f"recall@{args.top_k}={recall}  mrr={summary['mrr']}  "
            f"命中 {summary['hits']}/{summary['evaluated_cases']}"
            f"（另有 {summary['skipped_cases']} 条跳过）"
        )

    if summary["evaluated_cases"] == 0:
        print("没有可评测的用例：请向评测集添加指向真实资料的用例。", file=sys.stderr)
        return 2
    if args.min_recall is not None and summary["recall_at_k"] < args.min_recall:
        print(f"recall@k={summary['recall_at_k']} 低于门禁 {args.min_recall}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
