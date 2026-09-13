import re
from collections.abc import Iterator
from dataclasses import dataclass

_PAGE_MARKER_RE = re.compile(r"^\[第\s*(\d+)\s*页\]\s*")
_NUMBERED_HEADING_RE = re.compile(
    r"^(第\s*[一二三四五六七八九十百千0-9]+\s*[章节篇回部分]"
    r"|[一二三四五六七八九十]+\s*[、.．]"
    r"|（\s*[一二三四五六七八九十0-9]+\s*）"
    r"|\(\s*[一二三四五六七八九十0-9]+\s*\)"
    r"|[0-9]+\s*[、.．])\s*"
)


@dataclass(frozen=True)
class ChunkData:
    chunk_index: int
    content: str
    start_offset: int
    end_offset: int
    char_count: int
    section_title: str | None = None
    page_number: int | None = None


def split_text_into_chunks(
    text: str,
    chunk_size: int = 800,
    overlap: int = 120,
    min_chunk_size: int = 150,
    max_chunk_size: int = 1200,
) -> list[ChunkData]:
    return list(
        iter_text_chunks(
            text,
            chunk_size=chunk_size,
            overlap=overlap,
            min_chunk_size=min_chunk_size,
            max_chunk_size=max_chunk_size,
        )
    )


def iter_text_chunks(
    text: str,
    chunk_size: int = 800,
    overlap: int = 120,
    min_chunk_size: int = 150,
    max_chunk_size: int = 1200,
) -> Iterator[ChunkData]:
    if not text.strip():
        return

    next_index = 0
    current_parts: list[str] = []
    current_start: int | None = None
    current_end = 0
    current_section: str | None = None
    current_page: int | None = None

    for paragraph, start, end in _paragraphs_with_offsets(text):
        page_number, paragraph, start = _extract_page_marker(paragraph, start)
        if page_number is not None:
            if current_parts:
                yield _build_chunk(
                    next_index,
                    current_parts,
                    current_start or 0,
                    current_end,
                    current_section,
                    current_page,
                )
                next_index += 1
                current_parts, current_start = [], None
            current_page = page_number
            current_section = None
            if not paragraph:
                continue

        section = _section_title(paragraph)
        if section and current_parts:
            yield _build_chunk(
                next_index,
                current_parts,
                current_start or 0,
                current_end,
                current_section,
                current_page,
            )
            next_index += 1
            current_parts, current_start = [], None
        if section:
            current_section = section

        if len(paragraph) > max_chunk_size:
            if current_parts:
                yield _build_chunk(
                    next_index,
                    current_parts,
                    current_start or 0,
                    current_end,
                    current_section,
                    current_page,
                )
                next_index += 1
                current_parts, current_start = [], None
            for split_content, split_start, split_end in _split_long_text(paragraph, start, chunk_size, overlap):
                yield ChunkData(
                    chunk_index=next_index,
                    content=split_content,
                    start_offset=split_start,
                    end_offset=split_end,
                    char_count=len(split_content),
                    section_title=current_section,
                    page_number=current_page,
                )
                next_index += 1
            continue

        next_length = _joined_length(current_parts, paragraph)
        if (
            current_parts
            and next_length > chunk_size
            and (
                _joined_length(current_parts) >= min_chunk_size
                or next_length > max_chunk_size
            )
        ):
            completed = _build_chunk(
                next_index,
                current_parts,
                current_start or 0,
                current_end,
                current_section,
                current_page,
            )
            yield completed
            next_index += 1
            overlap_text = _tail_overlap(completed.content, overlap)
            current_parts = [overlap_text] if overlap_text else []
            current_start = (
                max(
                    completed.end_offset - len(overlap_text),
                    completed.start_offset,
                )
                if overlap_text
                else None
            )

        if current_start is None:
            current_start = start
        current_parts.append(paragraph)
        current_end = end

    if current_parts:
        yield _build_chunk(
            next_index,
            current_parts,
            current_start or 0,
            current_end,
            current_section,
            current_page,
        )


def _paragraphs_with_offsets(text: str) -> Iterator[tuple[str, int, int]]:
    cursor = 0
    while cursor <= len(text):
        separator = text.find("\n\n", cursor)
        end = len(text) if separator < 0 else separator
        block = text[cursor:end]
        leading_trim = len(block) - len(block.lstrip())
        trailing_trim = len(block) - len(block.rstrip())
        cleaned = block.strip()
        if cleaned:
            yield cleaned, cursor + leading_trim, end - trailing_trim
        if separator < 0:
            return
        cursor = separator + 2


def _split_long_text(
    text: str,
    base_offset: int,
    chunk_size: int,
    overlap: int,
) -> Iterator[tuple[str, int, int]]:
    start = 0
    while start < len(text):
        target_end = min(start + chunk_size, len(text))
        end = _find_boundary(text, start, target_end) if target_end < len(text) else target_end
        if end <= start:
            end = target_end
        content = text[start:end].strip()
        if content:
            leading_trim = len(text[start:end]) - len(text[start:end].lstrip())
            trailing_trim = len(text[start:end].rstrip())
            actual_start = base_offset + start + leading_trim
            actual_end = base_offset + start + trailing_trim
            yield content, actual_start, actual_end
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)


def _find_boundary(text: str, start: int, target_end: int) -> int:
    boundary_chars = "。！？!?；;\n"
    search_start = max(start, target_end - 220)
    for index in range(target_end, search_start, -1):
        if text[index - 1] in boundary_chars:
            return index
    return target_end


def _build_chunk(
    index: int,
    parts: list[str],
    start: int,
    end: int,
    section_title: str | None,
    page_number: int | None,
) -> ChunkData:
    content = "\n\n".join(part for part in parts if part).strip()
    return ChunkData(
        chunk_index=index,
        content=content,
        start_offset=start,
        end_offset=end,
        char_count=len(content),
        section_title=section_title,
        page_number=page_number,
    )


def _extract_page_marker(paragraph: str, start: int) -> tuple[int | None, str, int]:
    match = _PAGE_MARKER_RE.match(paragraph)
    if match is None:
        return None, paragraph, start

    remaining = paragraph[match.end() :]
    leading_trim = len(remaining) - len(remaining.lstrip())
    content = remaining.strip()
    return int(match.group(1)), content, start + match.end() + leading_trim


def _joined_length(parts: list[str], next_part: str | None = None) -> int:
    values = parts + ([next_part] if next_part else [])
    return len("\n\n".join(values))


def _tail_overlap(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    first_sentence = min(
        [idx for idx in (tail.find("。"), tail.find("！"), tail.find("？"), tail.find("\n")) if idx >= 0],
        default=-1,
    )
    if first_sentence >= 0 and first_sentence + 1 < len(tail):
        return tail[first_sentence + 1 :].strip()
    return tail.strip()


def _section_title(paragraph: str) -> str | None:
    first_line = paragraph.splitlines()[0].strip()
    if first_line.startswith("#"):
        return first_line.lstrip("#").strip()[:255] or None
    match = _NUMBERED_HEADING_RE.match(first_line)
    if match is not None:
        remainder = first_line[match.end() :].strip()
        # 句子式内容（如“1. 苹果是水果。”）是列表项，不是标题
        if remainder and len(remainder) <= 60 and not remainder.endswith(
            ("。", "！", "？", ";", "；")
        ):
            return remainder[:255] or None
        return None
    if len(first_line) <= 40 and not first_line.endswith(("。", "！", "？", ".", "!", "?")):
        return first_line
    return None
