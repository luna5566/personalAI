from __future__ import annotations

import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path

from app.ai.http_client import post_json_limited
from app.core.config import settings


class SpeechToTextProvider(ABC):
    @abstractmethod
    def transcribe(self, path: Path, mime_type: str | None = None) -> str:
        raise NotImplementedError


class DisabledSpeechToTextProvider(SpeechToTextProvider):
    def transcribe(self, path: Path, mime_type: str | None = None) -> str:
        raise RuntimeError(
            "语音转文字尚未启用。请先配置 SPEECH_TO_TEXT_PROVIDER，或改为上传文本资料。"
        )


class OpenAICompatibleSpeechToTextProvider(SpeechToTextProvider):
    def __init__(self, base_url: str | None, api_key: str | None, model: str) -> None:
        if not api_key:
            raise ValueError("SPEECH_TO_TEXT_API_KEY is required for openai_compatible provider")
        if not model:
            raise ValueError("SPEECH_TO_TEXT_MODEL is required for openai_compatible provider")
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.model = model

    def transcribe(self, path: Path, mime_type: str | None = None) -> str:
        detected_mime = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as audio_file:
            data = post_json_limited(
                f"{self.base_url}/audio/transcriptions",
                max_response_size_bytes=settings.ai_provider_max_response_size_bytes,
                headers={"Authorization": f"Bearer {self.api_key}"},
                data={"model": self.model},
                files={"file": (path.name, audio_file, detected_mime)},
                timeout=180,
            )
        text = data.get("text", "").strip()
        if not text:
            raise ValueError("Speech-to-text provider returned empty text")
        return text


def get_speech_to_text_provider() -> SpeechToTextProvider:
    if settings.speech_to_text_provider == "disabled":
        return DisabledSpeechToTextProvider()
    if settings.speech_to_text_provider == "openai_compatible":
        return OpenAICompatibleSpeechToTextProvider(
            base_url=settings.speech_to_text_base_url,
            api_key=settings.speech_to_text_api_key,
            model=settings.speech_to_text_model,
        )
    raise ValueError(
        f"Unsupported speech-to-text provider: {settings.speech_to_text_provider}"
    )
