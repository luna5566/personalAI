from types import SimpleNamespace

from app.services import parsing_service


def test_pdf_pages_are_joined_without_retaining_a_page_list(
    monkeypatch,
    tmp_path,
) -> None:
    pages = [
        SimpleNamespace(extract_text=lambda: " first page "),
        SimpleNamespace(extract_text=lambda: "   "),
        SimpleNamespace(extract_text=lambda: " third page "),
    ]
    monkeypatch.setattr(
        parsing_service,
        "PdfReader",
        lambda path: SimpleNamespace(pages=pages),
    )

    parsed = parsing_service._parse_pdf_file(tmp_path / "probe.pdf")

    assert parsed.raw_text == (
        "[第 1 页]\nfirst page\n\n\n[第 3 页]\nthird page"
    )
    assert parsed.metadata == {"parser": "pypdf", "page_count": 3}
