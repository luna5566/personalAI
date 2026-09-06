from uuid import uuid4

from app.rag.chunker import iter_text_chunks, split_text_into_chunks
from app.rag.citation_builder import build_citations
from app.services.retrieval_service import RetrievedChunk


def test_pdf_page_markers_are_saved_as_chunk_metadata() -> None:
    text = "[第 1 页]\n第一页内容。\n\n[第 2 页]\n第二页内容。"

    chunks = split_text_into_chunks(text, min_chunk_size=1)

    assert [chunk.page_number for chunk in chunks] == [1, 2]
    assert [chunk.content for chunk in chunks] == ["第一页内容。", "第二页内容。"]
    assert [text[chunk.start_offset : chunk.end_offset] for chunk in chunks] == [
        "第一页内容。",
        "第二页内容。",
    ]


def test_long_paragraph_chunking_is_lazy() -> None:
    generated = iter_text_chunks(
        "x" * 5000,
        chunk_size=200,
        overlap=20,
        max_chunk_size=300,
    )

    first = next(generated)

    assert first.chunk_index == 0
    assert first.content == "x" * 200
    assert not isinstance(generated, list)
    assert len(list(generated)) > 1


def test_citations_include_source_type_and_location() -> None:
    retrieved = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title="产品说明",
        source_type="pdf",
        chunk_index=1,
        content="引用内容",
        start_offset=10,
        end_offset=14,
        score=0.82,
        page_number=3,
    )

    citation = build_citations([retrieved])[0]

    assert citation.source_type.value == "pdf"
    assert citation.page_number == 3
