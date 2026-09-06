from types import SimpleNamespace

from app.services import parsing_service


def test_pdf_pages_are_joined_without_retaining_a_page_list(
    monkeypatch,
    tmp_path,
) -> None:
    pages = [
        SimpleNamespace(extract_text=lambda: " first page with enough text content "),
        SimpleNamespace(extract_text=lambda: "   "),
        SimpleNamespace(extract_text=lambda: " third page with enough text content "),
    ]
    monkeypatch.setattr(
        parsing_service,
        "PdfReader",
        lambda path: SimpleNamespace(pages=pages),
    )

    parsed = parsing_service._parse_pdf_file(tmp_path / "probe.pdf")

    assert parsed.raw_text == (
        "[第 1 页]\nfirst page with enough text content"
        "\n\n\n[第 3 页]\nthird page with enough text content"
    )
    assert parsed.metadata == {"parser": "pypdf", "page_count": 3}
