from dataclasses import dataclass
from uuid import UUID, uuid4

from app.rag.reranker import MMR_LAMBDA_DEFAULT, _tokenize, rerank_chunks


@dataclass
class FakeChunk:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    source_type: str
    chunk_index: int
    content: str
    start_offset: int
    end_offset: int
    score: float


def _chunk(content: str, score: float = 0.8, same_document: bool = False) -> FakeChunk:
    return FakeChunk(
        chunk_id=uuid4(),
        document_id=UUID(int=1) if same_document else uuid4(),
        document_title="文档",
        source_type="note",
        chunk_index=0,
        content=content,
        start_offset=0,
        end_offset=len(content),
        score=score,
    )


def test_near_duplicate_chunks_are_suppressed_by_mmr() -> None:
    base = "光合作用是植物利用光能将二氧化碳和水转化为有机物的过程"
    chunks = [
        _chunk(base + "甲" * 60, 0.9),
        _chunk(base + "乙" * 60, 0.85),
        _chunk("贝叶斯定理描述先验分布如何更新为后验概率" + "丙" * 60, 0.8),
    ]

    picked = rerank_chunks("光合作用", chunks, top_k=2)

    tails = [item.content[-1] for item in picked]
    assert tails == ["甲", "丙"], f"近重复内容应被 MMR 挤掉，实际选中 {tails}"


def test_distinct_chunks_are_not_suppressed() -> None:
    chunks = [
        _chunk("光合作用发生在叶绿体中，光反应产生 ATP。", 0.9),
        _chunk("暗反应通过卡尔文循环固定二氧化碳生成糖类。", 0.85),
        _chunk("呼吸作用分解有机物释放能量。", 0.8),
    ]

    picked = rerank_chunks("光合作用", chunks, top_k=3)

    assert len(picked) == 3
    assert [item.content for item in picked] == [
        chunk.content for chunk in chunks
    ]


def test_mmr_lambda_zero_disables_content_dedup() -> None:
    base = "光合作用是植物利用光能将二氧化碳和水转化为有机物的过程"
    chunks = [
        _chunk(base + "甲" * 60, 0.9),
        _chunk(base + "乙" * 60, 0.85),
        _chunk("贝叶斯定理描述先验分布" + "丙" * 60, 0.5),
    ]

    picked = rerank_chunks("光合作用", chunks, top_k=2, mmr_lambda=0.0)

    assert [item.content[-1] for item in picked] == ["甲", "乙"]


def test_mmr_lambda_is_configurable() -> None:
    base = "光合作用是植物利用光能将二氧化碳和水转化为有机物的过程"
    chunks = [
        _chunk(base + "甲" * 60, 0.9),
        _chunk(base + "乙" * 60, 0.85),
        _chunk("贝叶斯定理描述先验分布" + "丙" * 60, 0.72),
    ]

    weak = rerank_chunks("光合作用", chunks, top_k=2, mmr_lambda=0.1)
    strong = rerank_chunks("光合作用", chunks, top_k=2, mmr_lambda=0.9)

    # 弱惩罚容忍近重复，强惩罚坚持多样性
    assert [item.content[-1] for item in weak] == ["甲", "乙"]
    assert [item.content[-1] for item in strong] == ["甲", "丙"]


def test_default_lambda_constant_is_used() -> None:
    assert MMR_LAMBDA_DEFAULT == 0.4


def test_tokenize_uses_character_trigrams() -> None:
    tokens = _tokenize("光合作用 ATP")

    assert "光合" in tokens or "合作用" in tokens
    assert "ATP" in tokens or "atp" in tokens
    assert all(" " not in token for token in tokens)
    assert _tokenize("") == set()
    assert _tokenize("ab") == {"ab"}
