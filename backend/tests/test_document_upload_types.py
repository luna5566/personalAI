from pathlib import Path
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.api.routes.documents import _detect_source_type
from app.core.config import settings
from app.models.document import Document, DocumentSourceType
from app.services.parsing_service import parse_document
from app.storage import storage_service


def test_detects_image_upload_type() -> None:
    assert _detect_source_type("scan.png", "image/png") == DocumentSourceType.IMAGE
    assert _detect_source_type("scan.jpeg", None) == DocumentSourceType.IMAGE


def test_detects_audio_upload_type() -> None:
    assert _detect_source_type("voice.m4a", "audio/mp4") == DocumentSourceType.AUDIO
    assert _detect_source_type("voice.wav", None) == DocumentSourceType.AUDIO


def test_rejects_unknown_upload_type() -> None:
    with pytest.raises(HTTPException):
        _detect_source_type("archive.zip", "application/zip")


def test_rejects_image_upload_when_ocr_disabled(monkeypatch) -> None:
    from app.api.routes.documents import _reject_unavailable_media_upload

    monkeypatch.setattr(settings, "ocr_provider", "disabled")
    with pytest.raises(HTTPException) as exc_info:
        _reject_unavailable_media_upload(DocumentSourceType.IMAGE)
    assert exc_info.value.status_code == 400
    assert "OCR" in str(exc_info.value.detail)


def test_rejects_audio_upload_when_speech_disabled(monkeypatch) -> None:
    from app.api.routes.documents import _reject_unavailable_media_upload

    monkeypatch.setattr(settings, "speech_to_text_provider", "disabled")
    with pytest.raises(HTTPException) as exc_info:
        _reject_unavailable_media_upload(DocumentSourceType.AUDIO)
    assert exc_info.value.status_code == 400
    assert "语音" in str(exc_info.value.detail)


def test_allows_media_upload_when_providers_enabled(monkeypatch) -> None:
    from app.api.routes.documents import _reject_unavailable_media_upload

    monkeypatch.setattr(settings, "ocr_provider", "openai_compatible")
    monkeypatch.setattr(settings, "speech_to_text_provider", "openai_compatible")
    _reject_unavailable_media_upload(DocumentSourceType.IMAGE)
    _reject_unavailable_media_upload(DocumentSourceType.AUDIO)
    _reject_unavailable_media_upload(DocumentSourceType.PDF)


def test_image_parse_fails_clearly_when_ocr_disabled(tmp_path: Path) -> None:
    previous_storage_root = settings.storage_root
    settings.storage_root = tmp_path
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"not-really-an-image")
    document = Document(
        title="scan",
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        source_type=DocumentSourceType.IMAGE.value,
        file_path="scan.png",
        storage_backend="local",
        storage_scope=storage_service.current_storage_scope(),
        mime_type="image/png",
    )

    try:
        with pytest.raises(
            RuntimeError,
            match="图片文字识别失败，请检查 OCR Provider 配置后重试",
        ):
            parse_document(document)
    finally:
        settings.storage_root = previous_storage_root


def test_audio_parse_fails_clearly_when_speech_to_text_disabled(tmp_path: Path) -> None:
    previous_storage_root = settings.storage_root
    settings.storage_root = tmp_path
    audio_path = tmp_path / "voice.m4a"
    audio_path.write_bytes(b"not-really-audio")
    document = Document(
        title="voice",
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        source_type=DocumentSourceType.AUDIO.value,
        file_path="voice.m4a",
        storage_backend="local",
        storage_scope=storage_service.current_storage_scope(),
        mime_type="audio/mp4",
    )

    try:
        with pytest.raises(
            RuntimeError,
            match="音频转写失败，请检查语音转文字 Provider 配置后重试",
        ):
            parse_document(document)
    finally:
        settings.storage_root = previous_storage_root
