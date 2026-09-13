import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

from app.services.retrieval_service import RetrievedChunk


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "eval_retrieval.py"
    spec = importlib.util.spec_from_file_location("eval_retrieval", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("eval_retrieval", module)
    spec.loader.exec_module(module)
    return module


def _chunk(content: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title="标题",
        source_type="note",
        chunk_index=0,
        content=content,
        start_offset=0,
        end_offset=len(content),
        score=0.9,
    )


def test_relevant_ranks_by_document_id() -> None:
    module = _load_script()
    hit = _chunk("其他内容")
    miss = _chunk("无关内容")
    ranks = module.relevant_ranks(
        [miss, hit],
        frozenset({str(hit.document_id)}),
        (),
    )
    assert ranks == [2]


def test_relevant_ranks_by_keyword_is_case_insensitive() -> None:
    module = _load_script()
    ranks = module.relevant_ranks(
        [_chunk("没有提到主题"), _chunk("这里介绍了 PGVector 的用法")],
        frozenset(),
        ("pgvector",),
    )
    assert ranks == [2]


def test_relevant_ranks_without_hit_returns_empty() -> None:
    module = _load_script()
    assert module.relevant_ranks([_chunk("内容甲"), _chunk("内容乙")], frozenset(), ("不存在",)) == []


def test_summarize_reports_recall_and_mrr() -> None:
    module = _load_script()
    case_results = [
        {"status": "evaluated", "ranks": [1]},
        {"status": "evaluated", "ranks": [3]},
        {"status": "evaluated", "ranks": []},
        {"status": "skipped", "reason": "缺少期望", "ranks": []},
    ]
    summary = module.summarize(case_results)
    assert summary["total_cases"] == 4
    assert summary["evaluated_cases"] == 3
    assert summary["skipped_cases"] == 1
    assert summary["hits"] == 2
    assert summary["recall_at_k"] == round(2 / 3, 4)
    assert summary["mrr"] == round((1.0 + 1.0 / 3.0 + 0.0) / 3, 4)


def test_summarize_without_evaluated_cases_returns_none_metrics() -> None:
    module = _load_script()
    summary = module.summarize([{"status": "skipped", "reason": "x", "ranks": []}])
    assert summary["recall_at_k"] is None
    assert summary["mrr"] is None


def test_load_eval_cases_skips_blank_and_comment_lines(tmp_path) -> None:
    module = _load_script()
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "# 注释行\n"
        "\n"
        '{"question": "问题", "expected_keywords": ["关键词"]}\n',
        encoding="utf-8",
    )
    cases = module.load_eval_cases(path)
    assert len(cases) == 1
    assert cases[0]["question"] == "问题"
