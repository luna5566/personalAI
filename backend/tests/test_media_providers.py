import base64
import json
from pathlib import Path

from app.ai.ocr_provider import OpenAICompatibleOCRProvider
from app.ai.speech_provider import OpenAICompatibleSpeechToTextProvider


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.headers = {"content-length": str(len(self.body))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self, chunk_size: int):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]


def test_openai_compatible_ocr_provider(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "scan.png"
    image_bytes = b"image-bytes"
    image_path.write_bytes(image_bytes)
    captured = {}

    def fake_stream(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["parts"] = list(kwargs["content"])
        captured["json"] = json.loads(b"".join(captured["parts"]))
        captured["headers"] = kwargs["headers"]
        return FakeResponse({"choices": [{"message": {"content": "识别出的文字"}}]})

    monkeypatch.setattr("app.ai.http_client.httpx.stream", fake_stream)
    provider = OpenAICompatibleOCRProvider("https://example.test/v1", "secret", "vision-model")

    assert provider.extract_text(image_path, "image/png") == "识别出的文字"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.test/v1/chat/completions"
    image_url = captured["json"]["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")
    assert base64.b64decode(image_url.partition(",")[2]) == image_bytes
    body_size = sum(len(part) for part in captured["parts"])
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["headers"]["Content-Length"] == str(body_size)
    assert len(captured["parts"]) == 3


def test_ocr_request_base64_is_streamed_in_bounded_chunks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.ai import ocr_provider

    image_path = tmp_path / "large.png"
    image_bytes = b"x" * (ocr_provider.OCR_BASE64_INPUT_CHUNK_BYTES * 2 + 1)
    image_path.write_bytes(image_bytes)
    captured = {}

    def fail_read_bytes(path):
        raise AssertionError("OCR must not materialize the source file")

    def fake_stream(method, url, **kwargs):
        parts = list(kwargs["content"])
        captured["parts"] = parts
        captured["payload"] = json.loads(b"".join(parts))
        return FakeResponse({"choices": [{"message": {"content": "text"}}]})

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)
    monkeypatch.setattr("app.ai.http_client.httpx.stream", fake_stream)
    provider = OpenAICompatibleOCRProvider(
        "https://example.test/v1",
        "secret",
        "vision-model",
    )

    assert provider.extract_text(image_path, "image/png") == "text"

    base64_parts = captured["parts"][1:-1]
    assert len(base64_parts) == 3
    assert max(len(part) for part in base64_parts) == (
        ocr_provider.OCR_BASE64_INPUT_CHUNK_BYTES // 3 * 4
    )
    image_url = captured["payload"]["messages"][1]["content"][1][
        "image_url"
    ]["url"]
    assert base64.b64decode(image_url.partition(",")[2]) == image_bytes


def test_openai_compatible_speech_provider(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"audio-bytes")
    captured = {}

    def fake_stream(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["model"] = kwargs["data"]["model"]
        captured["filename"] = kwargs["files"]["file"][0]
        return FakeResponse({"text": "转写出的文字"})

    monkeypatch.setattr("app.ai.http_client.httpx.stream", fake_stream)
    provider = OpenAICompatibleSpeechToTextProvider("https://example.test/v1", "secret", "whisper-1")

    assert provider.transcribe(audio_path, "audio/wav") == "转写出的文字"
    assert captured == {
        "method": "POST",
        "url": "https://example.test/v1/audio/transcriptions",
        "model": "whisper-1",
        "filename": "voice.wav",
    }
