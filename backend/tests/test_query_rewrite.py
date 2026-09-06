from app.ai.llm_provider import LocalExtractiveLLMProvider, OpenAICompatibleLLMProvider
from app.services import chat_service


def _openai_provider(monkeypatch, content: str | None) -> OpenAICompatibleLLMProvider:
    provider = OpenAICompatibleLLMProvider(None, "key", "gpt-test")

    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["payload"] = kwargs["json"]
        message = {"role": "assistant", "content": content}
        return {"choices": [{"message": message}]}

    monkeypatch.setattr("app.ai.llm_provider.post_json_limited", fake_post)
    return provider, captured


def test_rewrite_retrieval_query_builds_standalone_prompt(monkeypatch) -> None:
    provider, captured = _openai_provider(monkeypatch, "本地 hash embedding 的限制")
    history = [
        ("user", "介绍一下本地 hash embedding"),
        ("assistant", "它用于本地联调。"),
    ]

    result = provider.rewrite_retrieval_query("它有什么限制？", history)

    assert result == "本地 hash embedding 的限制"
    user_message = captured["payload"]["messages"][-1]["content"]
    assert "它有什么限制？" in user_message
    assert "介绍一下本地 hash embedding" in user_message


def test_rewrite_retrieval_query_rejects_empty_or_oversized_output(monkeypatch) -> None:
    provider, _ = _openai_provider(monkeypatch, "   \n解释：这不应该是输出")
    history = [("user", "前面的问题")]

    assert provider.rewrite_retrieval_query("追问", history) is None

    provider, _ = _openai_provider(monkeypatch, "长" * 201)
    assert provider.rewrite_retrieval_query("追问", history) is None


def test_rewrite_retrieval_query_without_history_returns_none(monkeypatch) -> None:
    provider, captured = _openai_provider(monkeypatch, "查询")
    assert provider.rewrite_retrieval_query("问题", []) is None
    assert captured == {}


def test_base_provider_defaults_to_none() -> None:
    provider = LocalExtractiveLLMProvider()
    assert provider.rewrite_retrieval_query("问题", [("user", "历史")]) is None


def test_chat_service_falls_back_when_rewrite_fails(monkeypatch) -> None:
    class BrokenProvider(LocalExtractiveLLMProvider):
        def rewrite_retrieval_query(self, question, history):
            raise RuntimeError("provider down")

    query = chat_service._retrieval_query_with_rewrite(
        BrokenProvider(),
        "它有什么限制？",
        [("user", "介绍一下本地 hash embedding")],
    )
    assert query.startswith("它有什么限制？")
    assert "本地 hash embedding" in query


def test_chat_service_uses_rewrite_when_available(monkeypatch) -> None:
    class RewritingProvider(LocalExtractiveLLMProvider):
        def rewrite_retrieval_query(self, question, history):
            return "本地 hash embedding 的限制"

    query = chat_service._retrieval_query_with_rewrite(
        RewritingProvider(),
        "它有什么限制？",
        [("user", "介绍一下本地 hash embedding")],
    )
    assert query == "本地 hash embedding 的限制"


def test_chat_service_skips_rewrite_without_history(monkeypatch) -> None:
    class ShouldNotRewrite(LocalExtractiveLLMProvider):
        def rewrite_retrieval_query(self, question, history):
            raise AssertionError("should not be called")

    query = chat_service._retrieval_query_with_rewrite(
        ShouldNotRewrite(),
        "单独的问题",
        [],
    )
    assert query == "单独的问题"
