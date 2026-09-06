import gzip
import json
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from app.ai import http_client
from app.ai.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.ai.http_client import (
    PROVIDER_RESPONSE_READ_CHUNK_BYTES,
    ProviderResponseTooLargeError,
    post_json_limited,
)
from app.ai.llm_provider import OpenAICompatibleLLMProvider
from app.ai.ocr_provider import OpenAICompatibleOCRProvider
from app.ai.speech_provider import OpenAICompatibleSpeechToTextProvider
from app.core.config import settings


class FakeStreamResponse:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.chunks = chunks
        self.headers = headers or {}
        self.iterated_chunks = 0
        self.requested_chunk_sizes: list[int] = []
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.exited = True

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self, chunk_size: int):
        self.requested_chunk_sizes.append(chunk_size)
        for chunk in self.chunks:
            self.iterated_chunks += 1
            yield chunk


def test_limited_json_response_is_read_in_fixed_chunks(monkeypatch) -> None:
    response = FakeStreamResponse([b'{"ok":', b"true}"])
    captured = {}

    def fake_stream(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)
        return response

    monkeypatch.setattr(http_client.httpx, "stream", fake_stream)

    result = post_json_limited(
        "https://example.test/data",
        max_response_size_bytes=64,
        json={"request": True},
        timeout=5,
    )

    assert result == {"ok": True}
    assert captured == {
        "method": "POST",
        "url": "https://example.test/data",
        "kwargs": {"json": {"request": True}, "timeout": 5},
    }
    assert response.requested_chunk_sizes == [
        PROVIDER_RESPONSE_READ_CHUNK_BYTES
    ]
    assert response.exited is True


def test_declared_oversized_response_is_rejected_without_reading(monkeypatch) -> None:
    response = FakeStreamResponse(
        [b"must-not-be-read"],
        headers={"content-length": "65"},
    )
    monkeypatch.setattr(
        http_client.httpx,
        "stream",
        lambda *args, **kwargs: response,
    )

    with pytest.raises(ProviderResponseTooLargeError):
        post_json_limited(
            "https://example.test/data",
            max_response_size_bytes=64,
        )

    assert response.iterated_chunks == 0
    assert response.exited is True


def test_chunked_oversized_response_stops_at_the_crossing_chunk(
    monkeypatch,
) -> None:
    response = FakeStreamResponse([b"x" * 32, b"y" * 33, b"never-read"])
    monkeypatch.setattr(
        http_client.httpx,
        "stream",
        lambda *args, **kwargs: response,
    )

    with pytest.raises(ProviderResponseTooLargeError):
        post_json_limited(
            "https://example.test/data",
            max_response_size_bytes=64,
        )

    assert response.iterated_chunks == 2
    assert response.exited is True


def test_compressed_response_is_limited_after_decompression(monkeypatch) -> None:
    decoded = json.dumps({"text": "x" * 4096}).encode("utf-8")
    compressed = gzip.compress(decoded)
    assert len(compressed) < 1024 < len(decoded)
    response = httpx.Response(
        200,
        headers={
            "content-encoding": "gzip",
            "content-length": str(len(compressed)),
        },
        stream=httpx.ByteStream(compressed),
        request=httpx.Request("POST", "https://example.test/data"),
    )
    monkeypatch.setattr(
        http_client.httpx,
        "stream",
        lambda *args, **kwargs: closing(response),
    )

    with pytest.raises(ProviderResponseTooLargeError):
        post_json_limited(
            "https://example.test/data",
            max_response_size_bytes=1024,
        )

    assert response.is_closed is True


@pytest.mark.parametrize("limit", [True, 0, -1, 1.5])
def test_invalid_response_limit_fails_before_network(monkeypatch, limit) -> None:
    monkeypatch.setattr(
        http_client.httpx,
        "stream",
        lambda *args, **kwargs: pytest.fail("network must not be called"),
    )

    with pytest.raises(ValueError, match="positive integer"):
        post_json_limited(
            "https://example.test/data",
            max_response_size_bytes=limit,
        )


def test_all_openai_compatible_calls_apply_the_shared_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    endpoints: list[str] = []

    def fake_stream(method, url, **kwargs):
        assert method == "POST"
        endpoints.append(url)
        return FakeStreamResponse(
            [b"must-not-be-read"],
            headers={"content-length": "65"},
        )

    monkeypatch.setattr(http_client.httpx, "stream", fake_stream)
    monkeypatch.setattr(settings, "ai_provider_max_response_size_bytes", 64)
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"image")
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"audio")
    llm = OpenAICompatibleLLMProvider(
        "https://example.test/v1",
        "secret",
        "chat-model",
    )
    embedding = OpenAICompatibleEmbeddingProvider(
        "https://example.test/v1",
        "secret",
        "embedding-model",
        1536,
    )
    ocr = OpenAICompatibleOCRProvider(
        "https://example.test/v1",
        "secret",
        "vision-model",
    )
    speech = OpenAICompatibleSpeechToTextProvider(
        "https://example.test/v1",
        "secret",
        "speech-model",
    )
    calls = [
        lambda: llm.answer_with_context("question", "context"),
        lambda: llm.organize_with_context("summary", "context"),
        lambda: embedding.embed_texts(["text"]),
        lambda: ocr.extract_text(image_path, "image/png"),
        lambda: speech.transcribe(audio_path, "audio/wav"),
    ]

    for call in calls:
        with pytest.raises(ProviderResponseTooLargeError):
            call()

    assert endpoints == [
        "https://example.test/v1/chat/completions",
        "https://example.test/v1/chat/completions",
        "https://example.test/v1/embeddings",
        "https://example.test/v1/chat/completions",
        "https://example.test/v1/audio/transcriptions",
    ]
