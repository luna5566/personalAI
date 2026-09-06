from app.core.request_limits import RAG_CONTEXT_MAX_LENGTH
from app.services.retrieval_service import RetrievedChunk


def build_context(
    chunks: list[RetrievedChunk],
    max_chars: int = RAG_CONTEXT_MAX_LENGTH,
) -> str:
    if max_chars <= 0:
        return ""
    parts: list[str] = []
    used_chars = 0

    for index, chunk in enumerate(chunks, start=1):
        location = _location_label(chunk)
        text = (
            f"[资料 {index}]\n"
            f"标题：{chunk.document_title}\n"
            f"位置：{location}\n"
            f"片段：{chunk.content.strip()}"
        )
        separator_length = 2 if parts else 0
        remaining = max_chars - used_chars - separator_length
        if remaining <= 0:
            break
        if len(text) > remaining:
            if parts:
                break
            text = text[:remaining]
        parts.append(text)
        used_chars += separator_length + len(text)

    return "\n\n".join(parts)


def _location_label(chunk: RetrievedChunk) -> str:
    if chunk.page_number:
        return f"第 {chunk.page_number} 页"
    if chunk.section_title:
        return chunk.section_title
    return f"片段 {chunk.chunk_index + 1}"
