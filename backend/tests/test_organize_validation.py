from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes import organize as organize_routes
from app.models.document import DocumentSourceType, DocumentStatus
from app.schemas.organize import OrganizeCollectionRequest, OrganizeDocumentRequest
from app.services import organize_service


class RollbackSession:
    def __init__(self) -> None:
        self.connection_checked_out = True
        self.rollbacks = 0

    def rollback(self):
        self.connection_checked_out = False
        self.rollbacks += 1


def test_rejects_document_that_is_not_indexed(monkeypatch) -> None:
    document = SimpleNamespace(
        id=uuid4(),
        status=DocumentStatus.FAILED.value,
    )
    monkeypatch.setattr(
        organize_service.document_service,
        "get_document_reference",
        lambda *args: document,
    )

    with pytest.raises(ValueError, match="尚未完成索引"):
        organize_service.organize_document(
            RollbackSession(),
            uuid4(),
            OrganizeDocumentRequest(document_id=document.id),
        )


def test_rejects_indexed_document_without_chunks(monkeypatch) -> None:
    document = SimpleNamespace(
        id=uuid4(),
        status=DocumentStatus.INDEXED.value,
    )
    monkeypatch.setattr(
        organize_service.document_service,
        "get_document_reference",
        lambda *args: document,
    )
    monkeypatch.setattr(organize_service, "_document_chunks", lambda *args, **kwargs: [])

    with pytest.raises(ValueError, match="没有可整理"):
        organize_service.organize_document(
            RollbackSession(),
            uuid4(),
            OrganizeDocumentRequest(document_id=document.id),
        )


def test_collection_tag_without_matches_does_not_fall_back_to_all_documents(monkeypatch) -> None:
    monkeypatch.setattr(
        organize_service.tag_service,
        "document_ids_for_tags",
        lambda *args, **kwargs: [],
    )

    with pytest.raises(ValueError, match="所选范围内没有可整理"):
        organize_service.organize_collection(
            RollbackSession(),
            uuid4(),
            OrganizeCollectionRequest(tag="空标签"),
        )


def test_saved_organize_result_keeps_ai_source_type_and_provenance(monkeypatch) -> None:
    source_id = uuid4()
    captured = {}
    note = SimpleNamespace(
        id=uuid4(),
        source_type=DocumentSourceType.AI_GENERATED.value,
        metadata_={"source_document_ids": [str(source_id)]},
    )

    def create_note(*args, **kwargs):
        captured.update(kwargs)
        return note

    monkeypatch.setattr(
        organize_service.document_service,
        "create_note",
        create_note,
    )
    db = SimpleNamespace()

    saved = organize_service._save_result_note(
        db,
        uuid4(),
        "整理结果",
        "整理后的正文",
        [source_id],
    )

    assert saved.source_type == DocumentSourceType.AI_GENERATED.value
    assert saved.metadata_["source_document_ids"] == [str(source_id)]
    assert captured == {
        "source_type": DocumentSourceType.AI_GENERATED,
        "metadata": {"source_document_ids": [str(source_id)]},
    }


def test_collection_context_is_bounded_and_represents_each_document() -> None:
    documents_with_chunks = []
    for index in range(3):
        document = SimpleNamespace(id=uuid4(), title=f"资料 {index + 1}")
        chunks = [
            SimpleNamespace(chunk_index=0, content=(f"内容{index + 1}" * 1000))
        ]
        documents_with_chunks.append((document, chunks))

    context = organize_service._context_from_chunks(
        documents_with_chunks,
        max_chars=1800,
    )

    assert len(context) <= 1800
    assert "标题：资料 1" in context
    assert "标题：资料 2" in context
    assert "标题：资料 3" in context


def test_document_state_conflict_returns_409(monkeypatch) -> None:
    def reject(*args, **kwargs):
        raise organize_service.OrganizeConflictError("资料尚未完成索引")

    monkeypatch.setattr(organize_service, "organize_document", reject)

    with pytest.raises(HTTPException) as captured:
        organize_routes.organize_document(
            OrganizeDocumentRequest(document_id=uuid4()),
            None,
            uuid4(),
        )

    assert captured.value.status_code == 409


def test_collection_size_validation_returns_400(monkeypatch) -> None:
    def reject(*args, **kwargs):
        raise organize_service.OrganizeValidationError("一次最多整理 20 份资料")

    monkeypatch.setattr(organize_service, "organize_collection", reject)

    with pytest.raises(HTTPException) as captured:
        organize_routes.organize_collection(
            OrganizeCollectionRequest(),
            None,
            uuid4(),
        )

    assert captured.value.status_code == 400


def test_organize_provider_runs_after_the_read_transaction_is_released(
    monkeypatch,
) -> None:
    db = RollbackSession()
    prepared = organize_service.PreparedOrganization(
        context="上下文",
        source_document_ids=[uuid4()],
        note_title="整理结果",
    )
    monkeypatch.setattr(
        organize_service,
        "_prepare_document_organization",
        lambda *args: prepared,
    )

    class Provider:
        def organize_with_context(self, mode, context):
            assert db.connection_checked_out is False
            return "结果"

    result = organize_service.organize_document(
        db,
        uuid4(),
        OrganizeDocumentRequest(document_id=uuid4()),
        llm_provider=Provider(),
    )

    assert result.result == "结果"
    assert db.rollbacks == 1
