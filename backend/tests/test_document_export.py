from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import authenticated_user_id, db_session
from app.api.routes.documents import router as documents_router
from app.core.exceptions import register_exception_handlers


class _Document:
    def __init__(self, title: str = "光合作用笔记") -> None:
        self.id = uuid4()
        self.user_id = uuid4()
        self.title = title
        self.source_type = "note"
        self.cleaned_text = "光合作用是植物利用光能的过程。"
        self.raw_text = ""
        self.summary = ""
        self.created_at = datetime(2026, 9, 13, tzinfo=UTC)


class _Session:
    def __init__(self, document) -> None:
        self._document = document

    def scalar(self, statement):
        return self._document

    def execute(self, statement):
        return []

    def rollback(self):
        pass


def _build_app(document, user_id=None) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(documents_router, prefix="/api")

    def override_db():
        yield _Session(document)

    app.dependency_overrides[db_session] = override_db
    app.dependency_overrides[authenticated_user_id] = lambda: (
        user_id or document.user_id
    )
    return TestClient(app)


def test_export_returns_markdown_with_front_matter(monkeypatch) -> None:
    document = _Document()
    monkeypatch.setattr(
        "app.services.tag_service.document_tag_names",
        lambda db, document_id: ["植物", "笔记"],
    )
    client = _build_app(document)

    response = client.get(f"/api/documents/{document.id}/export.md")

    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    body = response.text
    assert body.startswith("---\n")
    assert f'title: "{document.title}"' in body
    assert "source: note" in body
    assert "tags: [植物, 笔记]" in body
    assert "光合作用是植物利用光能的过程。" in body


def test_export_sanitizes_unsafe_filename(monkeypatch) -> None:
    document = _Document(title='第1章/导论: "绪论"?')
    monkeypatch.setattr(
        "app.services.tag_service.document_tag_names",
        lambda db, document_id: [],
    )
    client = _build_app(document)

    response = client.get(f"/api/documents/{document.id}/export.md")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    encoded_name = disposition.split("filename*=UTF-8''")[1]
    assert "/" not in encoded_name
    assert "?" not in encoded_name


def test_export_missing_document_returns_404() -> None:
    document = _Document()
    client = _build_app(None, document.user_id)

    response = client.get(f"/api/documents/{uuid4()}/export.md")

    assert response.status_code == 404
