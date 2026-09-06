import json
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from app.ai import http_client
from app.ai.llm_provider import OpenAICompatibleLLMProvider
from app.ai.output_validation import (
    PROVIDER_OUTPUT_TOO_LARGE_PUBLIC_MESSAGE,
    ProviderOutputTooLargeError,
    validate_provider_text_length,
)
from app.api.routes import chat as chat_routes
from app.api.routes import organize as organize_routes
from app.core.request_limits import (
    CHAT_ANSWER_MAX_LENGTH,
    DOCUMENT_SUMMARY_MAX_LENGTH,
    ENRICHMENT_TAG_OUTPUT_MAX_LENGTH,
    ORGANIZE_RESULT_MAX_LENGTH,
)
from app.schemas.chat import ChatQueryRequest
from app.schemas.organize import OrganizeDocumentRequest
from app.services import chat_service, enrichment_service, organize_service
from app.services.retrieval_service import RetrievedChunk


def _retrieved_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title="资料",
        source_type="note",
        chunk_index=0,
        content="相关内容",
        start_offset=0,
        end_offset=4,
        score=0.8,
    )


@pytest.mark.parametrize(
    "max_length",
    [
        CHAT_ANSWER_MAX_LENGTH,
        ORGANIZE_RESULT_MAX_LENGTH,
        DOCUMENT_SUMMARY_MAX_LENGTH,
        ENRICHMENT_TAG_OUTPUT_MAX_LENGTH,
    ],
)
def test_all_provider_text_limits_accept_exactly_the_limit_and_reject_one_more(
    max_length: int,
) -> None:
    exact = "x" * max_length

    assert validate_provider_text_length(
        exact,
        max_length=max_length,
        output_name="test output",
    ) is exact
    with pytest.raises(ProviderOutputTooLargeError):
        validate_provider_text_length(
            exact + "x",
            max_length=max_length,
            output_name="test output",
        )


def test_chat_rejects_oversized_answer_before_suggestions_or_persistence(
    monkeypatch,
) -> None:
    db = MagicMock()
    suggested = []

    class Provider:
        def answer_with_context(self, question, context, history):
            return "x" * (CHAT_ANSWER_MAX_LENGTH + 1)

        def suggested_questions(self, question, answer):
            suggested.append(answer)
            return []

    monkeypatch.setattr(
        chat_service.retrieval_service,
        "vector_search",
        lambda **kwargs: [_retrieved_chunk()],
    )

    with pytest.raises(ProviderOutputTooLargeError):
        chat_service.query(
            db,
            uuid4(),
            ChatQueryRequest(question="问题"),
            llm_provider=Provider(),
        )

    assert suggested == []
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_chat_accepts_answer_at_the_exact_limit(monkeypatch) -> None:
    db = MagicMock()
    answer = "x" * CHAT_ANSWER_MAX_LENGTH

    class Provider:
        def answer_with_context(self, question, context, history):
            return answer

        def suggested_questions(self, question, answer):
            return []

    monkeypatch.setattr(
        chat_service.retrieval_service,
        "vector_search",
        lambda **kwargs: [_retrieved_chunk()],
    )

    result = chat_service.query(
        db,
        uuid4(),
        ChatQueryRequest(question="问题"),
        llm_provider=Provider(),
    )

    assert result.answer == answer
    assistant = next(
        value
        for value in (call.args[0] for call in db.add.call_args_list)
        if getattr(value, "role", None) == "assistant"
    )
    assert assistant.content == answer
    db.commit.assert_called_once()


def test_openai_compatible_answer_can_pass_transport_limit_but_fail_business_limit(
    monkeypatch,
) -> None:
    db = MagicMock()
    payload = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": "x" * (CHAT_ANSWER_MAX_LENGTH + 1)
                    }
                }
            ]
        }
    ).encode()
    response = httpx.Response(
        200,
        content=payload,
        request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
    )
    monkeypatch.setattr(
        http_client.httpx,
        "stream",
        lambda *args, **kwargs: closing(response),
    )
    monkeypatch.setattr(
        chat_service.retrieval_service,
        "vector_search",
        lambda **kwargs: [_retrieved_chunk()],
    )
    provider = OpenAICompatibleLLMProvider(
        "https://example.test/v1",
        "secret",
        "chat-model",
    )

    with pytest.raises(ProviderOutputTooLargeError):
        chat_service.query(
            db,
            uuid4(),
            ChatQueryRequest(question="问题"),
            llm_provider=provider,
        )

    db.add.assert_not_called()
    db.commit.assert_not_called()
    assert response.is_closed is True


def test_organize_rejects_oversized_result_before_saving(monkeypatch) -> None:
    db = MagicMock()
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
    save_result = MagicMock()
    monkeypatch.setattr(organize_service, "_save_result_note", save_result)

    class Provider:
        def organize_with_context(self, mode, context):
            return "x" * (ORGANIZE_RESULT_MAX_LENGTH + 1)

    with pytest.raises(ProviderOutputTooLargeError):
        organize_service.organize_document(
            db,
            uuid4(),
            OrganizeDocumentRequest(document_id=uuid4(), save_as_note=True),
            llm_provider=Provider(),
        )

    save_result.assert_not_called()


def test_enrichment_rejects_oversized_summary_before_requesting_tags() -> None:
    calls = []

    class Provider:
        def organize_with_context(self, mode, context):
            calls.append(mode)
            return "x" * (DOCUMENT_SUMMARY_MAX_LENGTH + 1)

    with pytest.raises(enrichment_service.EnrichmentProviderError):
        enrichment_service.generate_document_enrichment(
            SimpleNamespace(title="资料"),
            [SimpleNamespace(chunk_index=0, content="内容")],
            provider=Provider(),
        )

    assert calls == ["summary"]


@pytest.mark.parametrize("route_name", ["chat", "organize"])
def test_provider_output_limit_has_a_stable_502_response(
    monkeypatch,
    route_name: str,
) -> None:
    if route_name == "chat":
        monkeypatch.setattr(
            chat_routes.chat_service,
            "query",
            lambda *args: (_ for _ in ()).throw(ProviderOutputTooLargeError()),
        )
        monkeypatch.setattr(
            chat_routes.ai_user_rate_limiter,
            "consume",
            lambda *args, **kwargs: None,
        )
        call = lambda: chat_routes.query(
            ChatQueryRequest(question="问题"),
            MagicMock(),
            uuid4(),
        )
    else:
        monkeypatch.setattr(
            organize_routes.organize_service,
            "organize_document",
            lambda *args: (_ for _ in ()).throw(ProviderOutputTooLargeError()),
        )
        monkeypatch.setattr(
            organize_routes.ai_user_rate_limiter,
            "consume",
            lambda *args, **kwargs: None,
        )
        call = lambda: organize_routes.organize_document(
            OrganizeDocumentRequest(document_id=uuid4()),
            MagicMock(),
            uuid4(),
        )

    with pytest.raises(HTTPException) as captured:
        call()

    assert captured.value.status_code == 502
    assert captured.value.detail == PROVIDER_OUTPUT_TOO_LARGE_PUBLIC_MESSAGE
