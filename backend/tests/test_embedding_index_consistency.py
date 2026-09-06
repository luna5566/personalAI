from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.ai.embedding_provider import (
    LocalHashEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from app.core.request_limits import (
    CHAT_SCOPE_DOCUMENT_LIMIT,
    CHAT_SCOPE_SOURCE_TYPE_LIMIT,
    CHAT_SCOPE_TAG_LIMIT,
)
from app.models.embedding import ChunkEmbedding
from app.services.embedding_service import _build_embeddings
from app.services.retrieval_service import RetrievalScopeValidationError, vector_search
from app.services.tag_service import DocumentTagValidationError


def test_local_hash_index_id_remains_backward_compatible() -> None:
    provider = LocalHashEmbeddingProvider("local_hash:1536", 1536)

    assert provider.index_id == "local_hash:1536"


def test_openai_index_id_tracks_model_dimensions_and_base_url() -> None:
    original = OpenAICompatibleEmbeddingProvider(
        "https://example.test/v1/", "secret-a", "embedding-small", 1536
    )
    same_index = OpenAICompatibleEmbeddingProvider(
        "https://example.test/v1", "secret-b", "embedding-small", 1536
    )
    other_model = OpenAICompatibleEmbeddingProvider(
        "https://example.test/v1", "secret-a", "embedding-large", 1536
    )
    other_base_url = OpenAICompatibleEmbeddingProvider(
        "https://other.test/v1", "secret-a", "embedding-small", 1536
    )

    assert original.index_id == same_index.index_id
    assert original.index_id != other_model.index_id
    assert original.index_id != other_base_url.index_id
    assert len(original.index_id) <= 128


def test_embeddings_store_index_id_instead_of_api_model_name() -> None:
    chunk = SimpleNamespace(id=uuid4(), user_id=uuid4(), document_id=uuid4())
    provider = OpenAICompatibleEmbeddingProvider(
        "https://example.test/v1", "secret", "embedding-small", 1536
    )

    embedding = _build_embeddings([chunk], [[0.0] * 1536], provider)[0]

    assert embedding.embedding_model == provider.index_id
    assert embedding.embedding_model != provider.model


def test_hnsw_index_has_explicit_build_options() -> None:
    index = next(
        index
        for index in ChunkEmbedding.__table__.indexes
        if index.name == "ix_chunk_embeddings_embedding_hnsw"
    )

    assert index.dialect_options["postgresql"]["using"] == "hnsw"
    assert index.dialect_options["postgresql"]["ops"] == {
        "embedding": "vector_l2_ops"
    }
    assert index.dialect_options["postgresql"]["with"] == {
        "m": 16,
        "ef_construction": 64,
    }


def test_vector_search_filters_out_embeddings_from_other_indexes() -> None:
    db = MagicMock()
    db.execute.side_effect = [None, [], []]
    provider = LocalHashEmbeddingProvider("local_hash:1536", 1536)

    assert vector_search(db, uuid4(), "search terms", provider=provider) == []

    hnsw_statement, hnsw_parameters = db.execute.call_args_list[0].args
    assert "hnsw.iterative_scan" in str(hnsw_statement)
    assert "hnsw.ef_search" in str(hnsw_statement)
    assert "hnsw.max_scan_tuples" in str(hnsw_statement)
    assert hnsw_parameters == {
        "ef_search": "100",
        "max_scan_tuples": "20000",
    }

    vector_statement = db.execute.call_args_list[1].args[0]
    params = vector_statement.compile().params.values()
    assert provider.index_id in params
    assert provider.dimensions in params


def test_retrieval_scope_uses_database_filters_in_both_searches() -> None:
    db = MagicMock()
    db.execute.side_effect = [None, [], []]
    provider = LocalHashEmbeddingProvider("local_hash:1536", 1536)
    document_id = uuid4()

    assert vector_search(
        db,
        uuid4(),
        "search terms",
        document_ids=[document_id],
        tag_names=["学习"],
        source_types=["note"],
        provider=provider,
    ) == []

    for call in db.execute.call_args_list[1:]:
        statement = call.args[0]
        sql = str(statement)
        params = statement.compile().params
        assert "EXISTS (SELECT 1" in sql
        assert "document_tags" in sql
        assert "tags" in sql
        assert "documents.source_type IN" in sql
        assert document_id in params["document_id_1"]
        assert "学习" in params["name_1"]
        assert "note" in params["source_type_1"]


@pytest.mark.parametrize(
    ("filters", "error_type"),
    [
        (
            {"document_ids": [uuid4() for _ in range(CHAT_SCOPE_DOCUMENT_LIMIT + 1)]},
            RetrievalScopeValidationError,
        ),
        (
            {"tag_names": [f"tag-{index}" for index in range(CHAT_SCOPE_TAG_LIMIT + 1)]},
            DocumentTagValidationError,
        ),
        (
            {"source_types": ["note"] * (CHAT_SCOPE_SOURCE_TYPE_LIMIT + 1)},
            RetrievalScopeValidationError,
        ),
    ],
)
def test_retrieval_rejects_oversized_scope_before_embedding_or_sql(
    filters,
    error_type,
) -> None:
    db = MagicMock()
    provider = MagicMock()

    with pytest.raises(error_type):
        vector_search(
            db,
            uuid4(),
            "search terms",
            provider=provider,
            **filters,
        )

    provider.embed_texts.assert_not_called()
    db.execute.assert_not_called()
