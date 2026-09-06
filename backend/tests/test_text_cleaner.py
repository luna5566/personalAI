import tracemalloc

import pytest

from app.utils.text_cleaner import clean_text


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("", ""),
        (" \t\r\n\r\n ", ""),
        ("a\nb", "a\nb"),
        ("a\n\nb", "a\n\nb"),
        ("a\n\n\nb", "a\n\nb"),
        ("  a \t b\r\n\r\n\r\n c \v d \r", "a b\n\nc d"),
        ("第一行\r第二行\r\n第三行", "第一行\n第二行\n第三行"),
    ],
)
def test_clean_text_preserves_normalized_semantics(
    source: str,
    expected: str,
) -> None:
    assert clean_text(source) == expected


def test_clean_text_does_not_build_full_line_lists() -> None:
    source = "alpha\t beta   gamma\r\n" * 50_000

    tracemalloc.start()
    try:
        cleaned = clean_text(source)
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert cleaned.startswith("alpha beta gamma\n")
    assert peak_bytes < len(source) * 3
