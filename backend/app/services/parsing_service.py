from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from pypdf import PdfReader

from app.ai.ocr_provider import get_ocr_provider
from app.ai.speech_provider import get_speech_to_text_provider
from app.models.document import Document, DocumentSourceType
from app.services.job_error_service import PublicJobError
from app.storage.storage_service import (
    StorageBackendChangedError,
    materialize_for_backend,
)


class DocumentParsingError(PublicJobError):
    pass


@dataclass(frozen=True)
class ParsedDocument:
    raw_text: str
    metadata: dict


def parse_document(document: Document) -> ParsedDocument:
    if document.source_type == DocumentSourceType.NOTE.value:
        return ParsedDocument(raw_text=document.raw_text or "", metadata=document.metadata_ or {})

    if not document.file_path:
        raise DocumentParsingError("资料缺少文件路径")
    if not document.storage_backend or not document.storage_scope:
        raise DocumentParsingError("资料缺少存储位置信息")

    try:
        with materialize_for_backend(
            document.file_path,
            document.storage_backend,
            document.storage_scope,
        ) as path:
            if document.source_type == DocumentSourceType.TXT.value:
                return _parse_text_file(path)
            if document.source_type == DocumentSourceType.MARKDOWN.value:
                return _parse_markdown_file(path)
            if document.source_type == DocumentSourceType.PDF.value:
                return _parse_pdf_file(path)
            if document.source_type == DocumentSourceType.IMAGE.value:
                return _parse_image_file(path, document.mime_type)
            if document.source_type == DocumentSourceType.AUDIO.value:
                return _parse_audio_file(path, document.mime_type)
            raise DocumentParsingError("暂不支持的资料类型")
    except (DocumentParsingError, StorageBackendChangedError):
        raise
    except Exception as exc:
        raise DocumentParsingError(
            _parsing_failure_message(document.source_type)
        ) from exc


def _parse_text_file(path: Path) -> ParsedDocument:
    text = _read_text(path)
    return ParsedDocument(raw_text=text, metadata={"parser": "text"})


def _parse_markdown_file(path: Path) -> ParsedDocument:
    text = _read_text(path)
    return ParsedDocument(raw_text=text, metadata={"parser": "markdown"})


def _parse_pdf_file(path: Path) -> ParsedDocument:
    reader = PdfReader(str(path))
    output = StringIO()
    wrote_page = False
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        cleaned = text.strip()
        if cleaned:
            if wrote_page:
                output.write("\n\n\n")
            output.write(f"[第 {index} 页]\n{cleaned}")
            wrote_page = True
    return ParsedDocument(
        raw_text=output.getvalue(),
        metadata={"parser": "pypdf", "page_count": len(reader.pages)},
    )


def _parse_image_file(path: Path, mime_type: str | None) -> ParsedDocument:
    text = get_ocr_provider().extract_text(path, mime_type=mime_type)
    return ParsedDocument(raw_text=text, metadata={"parser": "ocr"})


def _parse_audio_file(path: Path, mime_type: str | None) -> ParsedDocument:
    text = get_speech_to_text_provider().transcribe(path, mime_type=mime_type)
    return ParsedDocument(raw_text=text, metadata={"parser": "speech_to_text"})


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _parsing_failure_message(source_type: str) -> str:
    if source_type in {
        DocumentSourceType.TXT.value,
        DocumentSourceType.MARKDOWN.value,
    }:
        return "文本资料读取失败，请确认文件仍然存在且内容可读"
    if source_type == DocumentSourceType.PDF.value:
        return "PDF 解析失败，请确认文件完整且格式有效"
    if source_type == DocumentSourceType.IMAGE.value:
        return "图片文字识别失败，请检查 OCR Provider 配置后重试"
    if source_type == DocumentSourceType.AUDIO.value:
        return "音频转写失败，请检查语音转文字 Provider 配置后重试"
    return "资料解析失败，请确认文件格式有效后重试"
