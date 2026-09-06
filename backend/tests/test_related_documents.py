from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.deps import authenticated_user_id, db_session
from app.api.routes.documents import router as documents_router
from app.core.exceptions import register_exception_handlers
from app.models.document import DocumentStatus
from app.services import document_service
from app.services.retrieval_service import RetrievedChunk


class RollbackSession:
    def __init__(self) -> None:
        self.connection_checked_out = True
        self.rollbacks = 0

    def rollback(self):
        self.connection_checked_out = False
        self.rollbacks += 1


def test_related_documents_exclude_source_and_deduplicate_results(monkeypatch) -> None:
    source_id = uuid4()
    related_id = uuid4()
    source = SimpleNamespace(
        id=source_id,
        title="向量检索笔记",
        summary="记录混合检索和重排策略",
        body="向量检索结合关键词检索，可以改善召回质量。",
        status=DocumentStatus.INDEXED.value,
    )
    captured = {}
    db = RollbackSession()
    results = [
        RetrievedChunk(
            chunk_id=uuid4(),
            document_id=related_id,
            document_title="RAG 实践",
            source_type="note",
            chunk_index=0,
            content="混合检索需要合并向量和关键词结果。",
            start_offset=0,
            end_offset=19,
            score=0.82,
        ),
        RetrievedChunk(
            chunk_id=uuid4(),
            document_id=related_id,
            document_title="RAG 实践",
            source_type="note",
            chunk_index=1,
            content="重排用于改善最终上下文。",
            start_offset=20,
            end_offset=32,
            score=0.76,
        ),
    ]
    monkeypatch.setattr(
        document_service,
        "_get_related_document_source",
        lambda *args: source,
    )

    def fake_search(**kwargs):
        assert db.connection_checked_out is False
        db.connection_checked_out = True
        captured.update(kwargs)
        return results

    monkeypatch.setattr(document_service.retrieval_service, "vector_search", fake_search)

    related = document_service.find_related_documents(
        db,
        uuid4(),
        source_id,
        limit=5,
    )

    assert captured["exclude_document_ids"] == [source_id]
    assert "关键词检索" in captured["query"]
    assert len(related) == 1
    assert related[0].document_id == related_id
    assert related[0].score == 0.82
    assert db.rollbacks == 2
    assert db.connection_checked_out is False


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (document_service.RelatedDocumentNotFoundError("资料不存在"), 404),
        (
            document_service.RelatedDocumentUnavailableError(
                "资料尚未完成索引，暂时不能查找相关资料"
            ),
            409,
        ),
    ],
)
def test_related_documents_route_maps_public_errors(
    monkeypatch,
    error,
    expected_status,
) -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(documents_router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_user_id] = uuid4
    monkeypatch.setattr(
        document_service,
        "find_related_documents",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    response = TestClient(app).get(f"/documents/{uuid4()}/related")

    assert response.status_code == expected_status
    assert response.json() == {"message": str(error), "detail": str(error)}


def test_related_documents_route_hides_unexpected_value_error(monkeypatch) -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(documents_router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_user_id] = uuid4
    internal_error = ValueError(
        "https://internal.example/vector api_key=secret provider trace"
    )
    monkeypatch.setattr(
        document_service,
        "find_related_documents",
        lambda *args, **kwargs: (_ for _ in ()).throw(internal_error),
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        f"/documents/{uuid4()}/related"
    )

    assert response.status_code == 500
    assert response.json() == {
        "message": "服务器内部错误",
        "detail": "服务器内部错误",
    }
    assert "internal.example" not in response.text
    assert "api_key" not in response.text
