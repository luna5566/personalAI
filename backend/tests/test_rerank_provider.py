
import pytest

from app.ai import rerank_provider
from app.core.config import settings
from app.services.retrieval_service import RetrievedChunk, _apply_model_rerank


def _chunk(index: int, content: str, score: float) -> RetrievedChunk:
    from uuid import uuid4

    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title=f"资料{index}",
        source_type="note",
        chunk_index=index,
        content=content,
        start_offset=0,
        end_offset=len(content),
        score=score,
    )


def test_disabled_provider_raises() -> None:
    provider = rerank_provider.DisabledRerankProvider()
    with pytest.raises(RuntimeError):
        provider.rerank("问题", ["内容"], 2)


def test_cohere_provider_requires_api_key() -> None:
    with pytest.raises(ValueError):
        rerank_provider.CohereCompatibleRerankProvider(None, None, "rerank-v3.5")


def test_cohere_provider_parses_results(monkeypatch) -> None:
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["payload"] = kwargs["json"]
        return {
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.4},
            ]
        }

    monkeypatch.setattr(rerank_provider, "post_json_limited", fake_post)
    provider = rerank_provider.CohereCompatibleRerankProvider(None, "key", "rerank-v3.5")
    scores = provider.rerank("问题", ["甲", "乙"], top_n=2)

    assert scores == [0.4, 0.9]
    assert captured["url"].endswith("/rerank")
    assert captured["payload"]["model"] == "rerank-v3.5"
    assert captured["payload"]["documents"] == ["甲", "乙"]


def test_model_rerank_disabled_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rerank_provider", "disabled")
    chunks = [_chunk(0, "内容", 0.5)]
    assert _apply_model_rerank("问题", chunks, 2) is None


def test_model_rerank_rescores_and_truncates(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rerank_provider", "cohere")

    class FakeProvider(rerank_provider.RerankProvider):
        def rerank(self, query, documents, top_n):
            return [0.1, 0.9, 0.5]

    monkeypatch.setattr(
        "app.services.retrieval_service.get_rerank_provider",
        lambda: FakeProvider(),
    )
    chunks = [_chunk(i, f"内容{i}", 0.5) for i in range(3)]
    result = _apply_model_rerank("问题", chunks, top_k=2)

    assert result is not None
    assert [chunk.content for chunk in result] == ["内容1", "内容2"]
    assert result[0].score == 0.9


def test_model_rerank_failure_falls_back_to_heuristic(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rerank_provider", "cohere")

    class BrokenProvider(rerank_provider.RerankProvider):
        def rerank(self, query, documents, top_n):
            raise RuntimeError("provider down")

    monkeypatch.setattr(
        "app.services.retrieval_service.get_rerank_provider",
        lambda: BrokenProvider(),
    )
    chunks = [_chunk(i, f"内容{i}", 0.5) for i in range(3)]
    assert _apply_model_rerank("问题", chunks, 2) is None
