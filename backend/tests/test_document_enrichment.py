from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.ai.llm_provider import LocalExtractiveLLMProvider
from app.services import enrichment_service
from app.services.enrichment_service import _parse_generated_tags


def test_parses_json_and_text_tags() -> None:
    assert _parse_generated_tags('{"tags":["Python","向量检索"]}') == ["Python", "向量检索"]
    assert _parse_generated_tags("标签：学习，RAG、笔记") == ["学习", "RAG", "笔记"]


def test_generated_tags_are_limited_and_sentence_like_values_are_rejected() -> None:
    tags = _parse_generated_tags("一，二，三，四，五，六，这是一个远远超过二十个字符的完整句子不应该成为标签")

    assert tags == ["一", "二", "三", "四", "五"]


def test_enrichment_chunk_query_is_bounded_to_context_limit() -> None:
    statements = []

    class Session:
        def execute(self, statement):
            statements.append(statement)
            return []

    document_id = uuid4()

    chunks = enrichment_service.load_document_enrichment_chunks(
        Session(),
        document_id,
    )

    assert chunks == []
    assert len(statements) == 1
    statement = statements[0]
    assert statement._limit_clause.value == (
        enrichment_service.ENRICHMENT_CHUNK_LIMIT
    )
    sql = str(statement)
    assert "document_chunks.document_id" in sql
    assert "document_chunks.chunk_index" in sql
    assert [document_id] in statement.compile().params.values()


def test_enrichment_context_hard_limit_covers_first_chunk_and_separators() -> None:
    document = SimpleNamespace(title="历史宽资料")
    chunks = [
        SimpleNamespace(chunk_index=index, content="宽" * 10_000)
        for index in range(2)
    ]

    first_only = enrichment_service._build_context(
        document,
        chunks,
        max_chars=1_000,
    )
    multiple = enrichment_service._build_context(
        document,
        [
            SimpleNamespace(chunk_index=index, content="短内容")
            for index in range(10)
        ],
        max_chars=120,
    )

    assert len(first_only) == 1_000
    assert first_only.startswith("[资料 1]\n标题：历史宽资料")
    assert len(multiple) <= 120
    assert len(multiple) + 2 > 120 or multiple.count("\n\n") > 0


def test_local_provider_generates_summary_and_tags() -> None:
    provider = LocalExtractiveLLMProvider()
    context = "[资料 1]\n标题：RAG 学习笔记\n位置：片段 1\n片段：向量检索结合关键词检索可以提高召回质量。"

    summary = provider.organize_with_context("summary", context)
    tags = provider.organize_with_context("tags", context)

    assert "向量检索" in summary
    assert tags.startswith("标签：RAG 学习笔记")


def test_enrichment_provider_error_hides_internal_exception() -> None:
    document = SimpleNamespace(metadata_={})

    class Provider:
        def organize_with_context(self, mode, context):
            raise RuntimeError(
                "https://internal.example api_key=secret provider trace"
            )

    with pytest.raises(
        enrichment_service.EnrichmentProviderError,
        match="资料摘要和标签生成失败，请检查模型配置后重试",
    ) as exc_info:
        enrichment_service.enrich_document(
            SimpleNamespace(),
            SimpleNamespace(
                id="document-id",
                title="title",
                metadata_={},
            ),
            [SimpleNamespace(chunk_index=0, content="content")],
            provider=Provider(),
        )

    enrichment_service.record_enrichment_error(document, exc_info.value)

    assert document.metadata_["enrichment_error"] == (
        "资料摘要和标签生成失败，请检查模型配置后重试"
    )
    assert "internal.example" not in document.metadata_["enrichment_error"]


def test_enrichment_does_not_exceed_the_document_tag_limit(monkeypatch) -> None:
    existing_tags = [f"tag-{index}" for index in range(20)]
    applied = []
    monkeypatch.setattr(
        enrichment_service.tag_service,
        "document_tag_names",
        lambda *args: existing_tags,
    )
    monkeypatch.setattr(
        enrichment_service.tag_service,
        "set_document_tags",
        lambda db, user_id, document_id, tags: applied.extend(tags),
    )

    class Provider:
        def organize_with_context(self, mode, context):
            if mode == "summary":
                return "summary"
            return '{"tags":["new-tag"]}'

    document = SimpleNamespace(
        id="document-id",
        user_id="user-id",
        title="title",
        metadata_={},
        summary=None,
    )

    generated = enrichment_service.enrich_document(
        MagicMock(),
        document,
        [SimpleNamespace(chunk_index=0, content="content")],
        provider=Provider(),
    )

    assert generated == []
    assert applied == existing_tags
    assert document.metadata_["auto_tags"] == []
