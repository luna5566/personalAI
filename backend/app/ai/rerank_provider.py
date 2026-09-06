from __future__ import annotations

from abc import ABC, abstractmethod

from app.ai.http_client import post_json_limited
from app.core.config import settings


class RerankProvider(ABC):
    @abstractmethod
    def rerank(self, query: str, documents: list[str], top_n: int) -> list[float]:
        """返回与 documents 一一对应的 relevance score（0~1）。"""
        raise NotImplementedError


class DisabledRerankProvider(RerankProvider):
    def rerank(self, query: str, documents: list[str], top_n: int) -> list[float]:
        raise RuntimeError("Rerank Provider 尚未启用。请先配置 RERANK_PROVIDER。")


class CohereCompatibleRerankProvider(RerankProvider):
    """兼容 Cohere / Jina 等 `/rerank` 接口的模型重排 Provider。"""

    def __init__(self, base_url: str | None, api_key: str | None, model: str) -> None:
        if not api_key:
            raise ValueError("RERANK_API_KEY is required for cohere rerank provider")
        if not model:
            raise ValueError("RERANK_MODEL is required for cohere rerank provider")
        self.base_url = (base_url or "https://api.cohere.com/v1").rstrip("/")
        self.api_key = api_key
        self.model = model

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[float]:
        if not documents:
            return []
        data = post_json_limited(
            f"{self.base_url}/rerank",
            max_response_size_bytes=settings.ai_provider_max_response_size_bytes,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "query": query,
                "documents": documents,
                "top_n": max(1, min(top_n, len(documents))),
            },
            timeout=30,
        )
        scores = [0.0] * len(documents)
        for item in data.get("results", []):
            index = int(item["index"])
            if 0 <= index < len(scores):
                scores[index] = float(item.get("relevance_score", 0.0))
        return scores


def get_rerank_provider() -> RerankProvider:
    if settings.rerank_provider == "disabled":
        return DisabledRerankProvider()
    if settings.rerank_provider == "cohere":
        return CohereCompatibleRerankProvider(
            base_url=settings.rerank_base_url,
            api_key=settings.rerank_api_key,
            model=settings.rerank_model,
        )
    raise ValueError(f"Unsupported rerank provider: {settings.rerank_provider}")
