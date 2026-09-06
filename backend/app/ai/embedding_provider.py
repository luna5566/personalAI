from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from typing import Any

from app.ai.http_client import post_json_limited
from app.core.config import settings


class EmbeddingProvider(ABC):
    model: str
    dimensions: int
    index_id: str

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class LocalHashEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model: str, dimensions: int) -> None:
        self.model = model
        self.dimensions = dimensions
        # Keep the original identifier so existing local_hash indexes remain usable.
        self.index_id = model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_normalize(_hash_embedding(text, self.dimensions)) for text in texts]


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(self, base_url: str | None, api_key: str | None, model: str, dimensions: int) -> None:
        if not api_key:
            raise ValueError("EMBEDDING_API_KEY is required for openai_compatible embedding provider")
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.index_id = build_embedding_index_id(
            provider="openai_compatible",
            base_url=self.base_url,
            model=model,
            dimensions=dimensions,
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        data: dict[str, Any] = post_json_limited(
            f"{self.base_url}/embeddings",
            max_response_size_bytes=settings.ai_provider_max_response_size_bytes,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "input": texts,
                "dimensions": self.dimensions,
            },
            timeout=60,
        )
        sorted_items = sorted(data["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in sorted_items]


def get_embedding_provider() -> EmbeddingProvider:
    if settings.embedding_provider == "local_hash":
        return LocalHashEmbeddingProvider(
            model=f"local_hash:{settings.embedding_dimensions}",
            dimensions=settings.embedding_dimensions,
        )
    if settings.embedding_provider == "openai_compatible":
        return OpenAICompatibleEmbeddingProvider(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
    raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")


def build_embedding_index_id(
    *,
    provider: str,
    base_url: str | None,
    model: str,
    dimensions: int,
) -> str:
    if provider == "local_hash":
        return f"local_hash:{dimensions}"
    if provider != "openai_compatible":
        raise ValueError(f"Unsupported embedding provider: {provider}")

    normalized_base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
    base_url_hash = hashlib.sha256(
        normalized_base_url.encode("utf-8")
    ).hexdigest()[:16]
    model_identity = model.strip()
    index_id = f"openai_compatible:{model_identity}:{dimensions}:{base_url_hash}"
    if len(index_id) > 128:
        model_hash = hashlib.sha256(model_identity.encode("utf-8")).hexdigest()[:16]
        index_id = f"openai_compatible:model-{model_hash}:{dimensions}:{base_url_hash}"
    return index_id


def _hash_embedding(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    tokens = _tokenize(text)
    if not tokens:
        tokens = [text or "empty"]

    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
        index = int.from_bytes(digest[:8], "big") % dimensions
        sign = 1.0 if digest[8] % 2 == 0 else -1.0
        weight = 1.0 + (digest[9] / 255.0)
        vector[index] += sign * weight

    return vector


def _tokenize(text: str) -> list[str]:
    compact = text.strip().lower()
    if not compact:
        return []

    words: list[str] = []
    current = []
    for char in compact:
        if char.isascii() and char.isalnum():
            current.append(char)
            continue
        if current:
            words.append("".join(current))
            current = []
        if not char.isspace():
            words.append(char)
    if current:
        words.append("".join(current))
    return words


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
