from app.schemas.chat import Citation
from app.services.retrieval_service import RetrievedChunk


def build_citations(chunks: list[RetrievedChunk]) -> list[Citation]:
    return [
        Citation(
            document_id=chunk.document_id,
            document_title=chunk.document_title,
            source_type=chunk.source_type,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            text=_preview(chunk.content),
            score=round(chunk.score, 4),
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            page_number=chunk.page_number,
            section_title=chunk.section_title,
        )
        for chunk in chunks
    ]


def _preview(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."
