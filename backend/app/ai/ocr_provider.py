from __future__ import annotations

import base64
import json
import mimetypes
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

from app.ai.http_client import post_json_limited
from app.core.config import settings

OCR_BASE64_INPUT_CHUNK_BYTES = 57 * 1024
_OCR_BASE64_MARKER = "__PERSONAL_AI_OCR_IMAGE_BASE64__"


class OCRProvider(ABC):
    @abstractmethod
    def extract_text(self, path: Path, mime_type: str | None = None) -> str:
        raise NotImplementedError


class DisabledOCRProvider(OCRProvider):
    def extract_text(self, path: Path, mime_type: str | None = None) -> str:
        raise RuntimeError(
            "图片 OCR 尚未启用。请先配置 OCR_PROVIDER，或改为上传 TXT、Markdown、PDF。"
        )


class OpenAICompatibleOCRProvider(OCRProvider):
    def __init__(self, base_url: str | None, api_key: str | None, model: str) -> None:
        if not api_key:
            raise ValueError("OCR_API_KEY is required for openai_compatible OCR provider")
        if not model:
            raise ValueError("OCR_MODEL is required for openai_compatible OCR provider")
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.model = model

    def extract_text(self, path: Path, mime_type: str | None = None) -> str:
        detected_mime = mime_type or mimetypes.guess_type(path.name)[0] or "image/jpeg"
        prefix, suffix = _ocr_request_parts(self.model, detected_mime)
        encoded_size = ((path.stat().st_size + 2) // 3) * 4
        data = post_json_limited(
            f"{self.base_url}/chat/completions",
            max_response_size_bytes=settings.ai_provider_max_response_size_bytes,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Content-Length": str(len(prefix) + encoded_size + len(suffix)),
            },
            content=_iter_ocr_request_body(path, prefix, suffix),
            timeout=120,
        )
        text = data["choices"][0]["message"]["content"].strip()
        if not text:
            raise ValueError("OCR provider returned empty text")
        return text


def _ocr_request_parts(model: str, mime_type: str) -> tuple[bytes, bytes]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是 OCR 助手。准确提取图片中的全部文字，保持原有段落顺序，只输出识别文字。",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "请识别这张图片中的文字。"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                f"data:{mime_type};base64,"
                                f"{_OCR_BASE64_MARKER}"
                            )
                        },
                    },
                ],
            },
        ],
        "temperature": 0,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    prefix, marker, suffix = serialized.partition(_OCR_BASE64_MARKER)
    if not marker:
        raise RuntimeError("OCR request marker was not serialized")
    return prefix.encode("ascii"), suffix.encode("ascii")


def _iter_ocr_request_body(
    path: Path,
    prefix: bytes,
    suffix: bytes,
    *,
    chunk_size: int = OCR_BASE64_INPUT_CHUNK_BYTES,
) -> Iterator[bytes]:
    if chunk_size < 3 or chunk_size % 3:
        raise ValueError("OCR base64 chunk size must be a positive multiple of 3")
    yield prefix
    with path.open("rb") as image:
        while chunk := image.read(chunk_size):
            yield base64.b64encode(chunk)
    yield suffix


def get_ocr_provider() -> OCRProvider:
    if settings.ocr_provider == "disabled":
        return DisabledOCRProvider()
    if settings.ocr_provider == "openai_compatible":
        return OpenAICompatibleOCRProvider(
            base_url=settings.ocr_base_url,
            api_key=settings.ocr_api_key,
            model=settings.ocr_model,
        )
    raise ValueError(f"Unsupported OCR provider: {settings.ocr_provider}")
