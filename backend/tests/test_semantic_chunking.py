from app.rag.chunker import split_text_into_chunks


def test_chinese_numbered_headings_become_section_titles() -> None:
    text = "第一章 简介\n\n本章介绍背景。\n\n二、方法\n\n正文内容。"

    chunks = split_text_into_chunks(text, min_chunk_size=1)

    titles = [chunk.section_title for chunk in chunks]
    assert "简介" in titles
    assert "方法" in titles
    # 每个新章节的 chunk 从标题行开始，便于向量携带章节上下文
    first_of_section = chunks[[c.section_title for c in chunks].index("简介")]
    assert first_of_section.content.startswith("第一章 简介")


def test_numbered_list_sentences_are_not_headings() -> None:
    text = "背景\n\n1. 苹果是水果。\n\n2. 香蕉也是水果。"

    chunks = split_text_into_chunks(text, min_chunk_size=1)

    assert all(
        chunk.section_title in ("背景", None) or chunk.section_title == "背景"
        for chunk in chunks
    )
    assert all(chunk.section_title != "苹果是水果。" for chunk in chunks)
    assert all(chunk.section_title != "香蕉也是水果。" for chunk in chunks)


def test_packing_respects_max_chunk_size() -> None:
    paragraphs = "\n\n".join(f"小段落{index}。" for index in range(40))

    chunks = split_text_into_chunks(
        paragraphs,
        chunk_size=30,
        overlap=0,
        min_chunk_size=1,
        max_chunk_size=45,
    )

    assert chunks
    assert all(chunk.char_count <= 45 for chunk in chunks)


def test_markdown_headings_still_recognized() -> None:
    text = "# 标题甲\n\n内容甲。\n\n## 子标题\n\n内容乙。"

    chunks = split_text_into_chunks(text, min_chunk_size=1)

    titles = [chunk.section_title for chunk in chunks]
    assert "标题甲" in titles
    assert "子标题" in titles


def test_offsets_still_map_to_source_text() -> None:
    text = "第一章 简介\n\n本章介绍背景，包含一些细节。\n\n二、方法\n\n正文内容较多，用于验证偏移。"

    chunks = split_text_into_chunks(text, min_chunk_size=1)

    for chunk in chunks:
        assert text[chunk.start_offset : chunk.end_offset] == chunk.content
