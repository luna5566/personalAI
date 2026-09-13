from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import authenticated_user_id, db_session
from app.api.routes.documents import router as documents_router
from app.core.exceptions import register_exception_handlers
from app.core.request_limits import (
    DOCUMENT_FILENAME_MAX_LENGTH,
    DOCUMENT_MIME_TYPE_MAX_LENGTH,
    DOCUMENT_SEARCH_KEYWORD_MAX_LENGTH,
    DOCUMENT_TAG_LIMIT,
    NOTE_CONTENT_MAX_LENGTH,
    TAG_NAME_MAX_LENGTH,
    UPLOAD_TAGS_FORM_MAX_LENGTH,
)
from app.models.document import DocumentSourceType
from app.services import document_service, tag_service


def _documents_client() -> TestClient:
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(documents_router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_user_id] = uuid4
    return TestClient(app)


@pytest.mark.parametrize(
    ("params", "location"),
    [
        (
            {"keyword": "x" * (DOCUMENT_SEARCH_KEYWORD_MAX_LENGTH + 1)},
            "keyword",
        ),
        ({"tag": "x" * (TAG_NAME_MAX_LENGTH + 1)}, "tag"),
    ],
)
def test_document_filters_reject_oversized_values_before_querying(
    monkeypatch,
    params,
    location,
) -> None:
    queried = []
    monkeypatch.setattr(
        document_service,
        "list_documents",
        lambda **kwargs: queried.append(kwargs) or ([], 0),
    )

    response = _documents_client().get("/documents", params=params)

    assert response.status_code == 422
    assert response.json()["message"] == "文本长度超过限制"
    assert response.json()["detail"][0]["loc"] == ["query", location]
    assert queried == []


def test_note_rejects_oversized_content_before_service(monkeypatch) -> None:
    created = []
    monkeypatch.setattr(
        document_service,
        "create_note",
        lambda *args: created.append(args),
    )

    response = _documents_client().post(
        "/documents/note",
        json={"content": "x" * (NOTE_CONTENT_MAX_LENGTH + 1)},
    )

    assert response.status_code == 422
    assert response.json()["message"] == "文本长度超过限制"
    assert created == []


@pytest.mark.parametrize(
    ("filename", "content_type", "tags", "expected_message"),
    [
        (
            f"{'x' * (DOCUMENT_FILENAME_MAX_LENGTH - 3)}.txt",
            "text/plain",
            None,
            "文件名不能超过 255 个字符",
        ),
        (
            "note.txt",
            "text/plain;" + "x" * DOCUMENT_MIME_TYPE_MAX_LENGTH,
            None,
            "MIME 类型不能超过 128 个字符",
        ),
        (
            "note.txt",
            "text/plain",
            ",".join(f"tag-{index}" for index in range(DOCUMENT_TAG_LIMIT + 1)),
            "每份资料最多添加 20 个标签",
        ),
    ],
)
def test_upload_rejects_invalid_metadata_before_writing_storage(
    monkeypatch,
    filename,
    content_type,
    tags,
    expected_message,
) -> None:
    storage_calls = []

    async def save_upload(*args, **kwargs):
        storage_calls.append((args, kwargs))
        return "documents/should-not-exist.txt", 1

    monkeypatch.setattr(
        "app.api.routes.documents.storage_service.save_upload",
        save_upload,
    )
    data = {"tags": tags} if tags is not None else None

    response = _documents_client().post(
        "/documents/upload",
        files={"file": (filename, b"content", content_type)},
        data=data,
    )

    assert response.status_code == 422
    assert response.json() == {
        "message": expected_message,
        "detail": expected_message,
    }
    assert storage_calls == []


def test_upload_tags_form_limit_is_enforced_before_writing_storage(
    monkeypatch,
) -> None:
    storage_calls = []

    async def save_upload(*args, **kwargs):
        storage_calls.append((args, kwargs))
        return "documents/should-not-exist.txt", 1

    monkeypatch.setattr(
        "app.api.routes.documents.storage_service.save_upload",
        save_upload,
    )

    response = _documents_client().post(
        "/documents/upload",
        files={"file": ("note.txt", b"content", "text/plain")},
        data={"tags": "x" * (UPLOAD_TAGS_FORM_MAX_LENGTH + 1)},
    )

    assert response.status_code == 422
    assert response.json()["message"] == "文本长度超过限制"
    assert storage_calls == []


def test_tag_service_rejects_oversized_collections_before_sql() -> None:
    db = MagicMock()

    with pytest.raises(
        tag_service.DocumentTagValidationError,
        match="每份资料最多添加 20 个标签",
    ):
        tag_service.set_document_tags(
            db,
            uuid4(),
            uuid4(),
            [f"tag-{index}" for index in range(DOCUMENT_TAG_LIMIT + 1)],
        )

    db.execute.assert_not_called()
    db.add_all.assert_not_called()
    db.flush.assert_not_called()


def test_tag_lookup_rejects_oversized_collections_before_sql() -> None:
    db = MagicMock()

    with pytest.raises(
        tag_service.DocumentTagValidationError,
        match="每份资料最多添加 20 个标签",
    ):
        tag_service.document_ids_for_tags(
            db,
            uuid4(),
            [f"tag-{index}" for index in range(DOCUMENT_TAG_LIMIT + 1)],
        )

    db.scalars.assert_not_called()


@pytest.mark.parametrize(
    ("original_filename", "mime_type"),
    [
        ("x" * (DOCUMENT_FILENAME_MAX_LENGTH + 1), "text/plain"),
        ("note.txt", "x" * (DOCUMENT_MIME_TYPE_MAX_LENGTH + 1)),
    ],
)
def test_file_document_service_rejects_invalid_metadata_before_sql(
    original_filename,
    mime_type,
) -> None:
    db = MagicMock()

    with pytest.raises(document_service.FileDocumentMetadataValidationError):
        document_service.add_file_document(
            db=db,
            user_id=uuid4(),
            title="note",
            source_type=DocumentSourceType.TXT,
            file_path="documents/note.txt",
            original_filename=original_filename,
            file_size=1,
            mime_type=mime_type,
        )

    db.add.assert_not_called()
    db.flush.assert_not_called()


def test_note_service_rejects_oversized_content_before_cleaning_or_sql(
    monkeypatch,
) -> None:
    db = MagicMock()
    cleaned = []
    monkeypatch.setattr(
        document_service,
        "clean_text",
        lambda content: cleaned.append(content) or content,
    )
    payload = document_service.NoteCreate.model_construct(
        content="x" * (NOTE_CONTENT_MAX_LENGTH + 1),
        title=None,
        tags=[],
    )

    with pytest.raises(document_service.NoteContentValidationError):
        document_service.create_note(db, uuid4(), payload)

    assert cleaned == []
    db.add.assert_not_called()
    db.flush.assert_not_called()
