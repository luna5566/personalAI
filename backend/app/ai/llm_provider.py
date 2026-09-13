from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterator
from typing import Any

from app.ai.http_client import iter_openai_chat_completion_deltas, post_json_limited
from app.core.config import settings


class LLMProvider(ABC):
    @abstractmethod
    def answer_with_context(
        self,
        question: str,
        context: str,
        history: list[tuple[str, str]] | None = None,
    ) -> str:
        raise NotImplementedError

    def stream_answer_with_context(
        self,
        question: str,
        context: str,
        history: list[tuple[str, str]] | None = None,
    ) -> Iterator[str]:
        answer = self.answer_with_context(question, context, history=history)
        chunk_size = 48
        for index in range(0, len(answer), chunk_size):
            yield answer[index : index + chunk_size]

    def suggested_questions(self, question: str, answer: str) -> list[str]:
        return [
            "帮我把这些内容整理成要点",
            "这些资料之间有什么联系？",
            "基于这些资料给我一个行动计划",
        ]

    def rewrite_retrieval_query(
        self,
        question: str,
        history: list[tuple[str, str]],
    ) -> str | None:
        """把带上下文依赖的追问改写成独立检索查询；不支持时返回 None。"""
        return None

    def organize_with_context(self, mode: str, context: str) -> str:
        prompt = f"整理方式：{mode}\n\n资料：\n{context}"
        return self.answer_with_context(prompt, context)


class LocalExtractiveLLMProvider(LLMProvider):
    def answer_with_context(
        self,
        question: str,
        context: str,
        history: list[tuple[str, str]] | None = None,
    ) -> str:
        if not context.strip():
            return "我在你的资料中没有找到足够依据。可以换个问法，或添加更多相关资料。"

        snippets = _extract_snippets(context)
        if not snippets:
            return "我检索到了相关资料，但没有足够清晰的片段可以回答。"

        lines = [
            "根据你的资料，可以先这样理解：",
            "",
        ]
        for index, snippet in enumerate(snippets[:3], start=1):
            lines.append(f"{index}. {snippet}")

        lines.extend(
            [
                "",
                "这是本地开发模式生成的回答，主要用于验证检索、引用和问答链路。接入真实大模型后，回答会更自然，也能做更强的归纳和联想。",
            ]
        )
        return "\n".join(lines)

    def organize_with_context(self, mode: str, context: str) -> str:
        snippets = _extract_snippets(context)
        if not snippets:
            return "没有找到可整理的资料内容。"

        if mode == "summary":
            return _local_summary(snippets)
        if mode == "outline":
            return _local_outline(snippets)
        if mode == "key_points":
            return _local_key_points(snippets)
        if mode == "action_items":
            return _local_action_items(snippets)
        if mode == "themes":
            return _local_themes(snippets)
        if mode == "connections":
            return _local_connections(snippets)
        if mode == "article_outline":
            return _local_article_outline(snippets)
        if mode == "study_plan":
            return _local_study_plan(snippets)
        if mode == "tags":
            return _local_tags(context, snippets)
        return _local_summary(snippets)


class OpenAICompatibleLLMProvider(LLMProvider):
    def __init__(self, base_url: str | None, api_key: str | None, model: str | None) -> None:
        if not api_key:
            raise ValueError("LLM_API_KEY is required for openai_compatible LLM provider")
        if not model:
            raise ValueError("LLM_MODEL is required for openai_compatible LLM provider")
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.model = model

    def answer_with_context(
        self,
        question: str,
        context: str,
        history: list[tuple[str, str]] | None = None,
    ) -> str:
        data: dict[str, Any] = post_json_limited(
            f"{self.base_url}/chat/completions",
            max_response_size_bytes=settings.ai_provider_max_response_size_bytes,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": _chat_messages(question, context, history or []),
                "temperature": 0.2,
            },
            timeout=90,
        )
        return data["choices"][0]["message"]["content"]

    def rewrite_retrieval_query(
        self,
        question: str,
        history: list[tuple[str, str]],
    ) -> str | None:
        recent_turns = "\n".join(
            f"{'用户' if role == 'user' else '助手'}：{content.strip()[:300]}"
            for role, content in history[-4:]
            if content.strip()
        )
        if not recent_turns:
            return None
        prompt = (
            "你是检索查询改写助手。根据最近对话，把用户的新问题改写成一条"
            "不依赖上下文即可理解的独立检索查询。保留原问题的语言，"
            "只输出查询本身，不要解释、不要加引号。\n\n"
            f"最近对话：\n{recent_turns}\n\n"
            f"新问题：{question.strip()}\n\n"
            "独立检索查询："
        )
        data: dict[str, Any] = post_json_limited(
            f"{self.base_url}/chat/completions",
            max_response_size_bytes=settings.ai_provider_max_response_size_bytes,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "你只输出改写后的检索查询。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
            },
            timeout=30,
        )
        lines = [
            line.strip().strip('"“”')
            for line in (data["choices"][0]["message"]["content"] or "").splitlines()
        ]
        if not lines or not lines[0] or any(lines[1:]) or len(lines[0]) > 200:
            return None
        return lines[0]

    def stream_answer_with_context(
        self,
        question: str,
        context: str,
        history: list[tuple[str, str]] | None = None,
    ) -> Iterator[str]:
        yield from iter_openai_chat_completion_deltas(
            f"{self.base_url}/chat/completions",
            max_response_size_bytes=settings.ai_provider_max_response_size_bytes,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": _chat_messages(question, context, history or []),
                "temperature": 0.2,
                "stream": True,
            },
            timeout=90,
        )

    def organize_with_context(self, mode: str, context: str) -> str:
        data: dict[str, Any] = post_json_limited(
            f"{self.base_url}/chat/completions",
            max_response_size_bytes=settings.ai_provider_max_response_size_bytes,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": _organize_system_prompt()},
                    {"role": "user", "content": f"整理方式：{mode}\n\n资料：\n{context}"},
                ],
                "temperature": 0.2,
            },
            timeout=90,
        )
        return data["choices"][0]["message"]["content"]


def get_llm_provider() -> LLMProvider:
    if settings.llm_provider == "local_extractive":
        return LocalExtractiveLLMProvider()
    if settings.llm_provider == "openai_compatible":
        return OpenAICompatibleLLMProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )
    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")


def _system_prompt() -> str:
    return (
        "你是一个个人资料知识助手。只能基于用户提供的资料回答。"
        "不要使用资料外的常识、猜测或编造内容来补全答案。"
        "如果资料没有明确依据，要直接说明无法确定，并告诉用户可以补充什么资料。"
        "回答要具体、清楚，优先归纳资料中的事实、观点、关系和行动项。"
        "不要伪造引用编号；引用来源由系统单独返回。"
    )


def _chat_messages(
    question: str,
    context: str,
    history: list[tuple[str, str]],
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": _system_prompt()}]
    for role, content in history[-6:]:
        if role not in {"user", "assistant"} or not content.strip():
            continue
        messages.append({"role": role, "content": content[:2000]})
    messages.append(
        {
            "role": "user",
            "content": f"当前问题：{question}\n\n检索到的资料：\n{context}",
        }
    )
    return messages


def _organize_system_prompt() -> str:
    return (
        "你是一个个人资料整理助手。只能基于提供的资料进行总结、归纳、提纲或计划生成。"
        "资料不足时要明确说明。输出要结构清晰，适合保存为笔记。"
    )


def _extract_snippets(context: str) -> list[str]:
    snippets: list[str] = []
    for block in context.split("[资料 "):
        if "片段：" not in block:
            continue
        snippet = block.split("片段：", 1)[1].strip()
        snippet = " ".join(snippet.split())
        if snippet:
            snippets.append(snippet[:260])
    return snippets


def _local_summary(snippets: list[str]) -> str:
    return "总结：\n" + "\n".join(f"- {snippet}" for snippet in snippets[:5])


def _local_outline(snippets: list[str]) -> str:
    lines = ["大纲："]
    for index, snippet in enumerate(snippets[:5], start=1):
        lines.append(f"{index}. {snippet[:80]}")
    return "\n".join(lines)


def _local_key_points(snippets: list[str]) -> str:
    return "知识点：\n" + "\n".join(f"- {snippet[:120]}" for snippet in snippets[:8])


def _local_action_items(snippets: list[str]) -> str:
    return "行动项：\n" + "\n".join(f"- 复盘并整理：{snippet[:80]}" for snippet in snippets[:5])


def _local_themes(snippets: list[str]) -> str:
    return "主题归纳：\n" + "\n".join(f"- 主题 {index}：{snippet[:100]}" for index, snippet in enumerate(snippets[:5], start=1))


def _local_connections(snippets: list[str]) -> str:
    if len(snippets) == 1:
        return f"关联分析：\n- 当前只有一个主要片段：{snippets[0][:120]}"
    return "关联分析：\n" + "\n".join(
        f"- 资料 {index} 与前后内容可能围绕同一主题展开：{snippet[:90]}" for index, snippet in enumerate(snippets[:5], start=1)
    )


def _local_article_outline(snippets: list[str]) -> str:
    return "\n".join(
        [
            "文章大纲：",
            "1. 引入：说明资料中的核心问题",
            f"2. 主体一：{snippets[0][:80]}",
            f"3. 主体二：{snippets[1][:80] if len(snippets) > 1 else snippets[0][:80]}",
            "4. 结尾：总结可执行结论",
        ]
    )


def _local_study_plan(snippets: list[str]) -> str:
    return "\n".join(
        [
            "学习计划：",
            f"- 第 1 步：阅读并标记重点：{snippets[0][:80]}",
            "- 第 2 步：整理成自己的笔记",
            "- 第 3 步：用提问方式复习",
            "- 第 4 步：一周后回顾并补充资料",
        ]
    )


def _local_tags(context: str, snippets: list[str]) -> str:
    titles = [item.strip() for item in re.findall(r"^标题：(.+)$", context, flags=re.MULTILINE)]
    ascii_terms = re.findall(r"[A-Za-z][A-Za-z0-9_+#.-]{2,}", " ".join(snippets))
    cjk_segments = re.findall(r"[\u4e00-\u9fff]{2,}", " ".join(snippets))
    cjk_terms: list[str] = []
    for segment in cjk_segments:
        if len(segment) <= 8:
            cjk_terms.append(segment)
        else:
            cjk_terms.extend(segment[index : index + 4] for index in range(0, min(len(segment) - 3, 12), 2))

    stop_words = {"资料", "内容", "这个", "可以", "进行", "以及", "通过", "一个", "我们", "需要"}
    ranked = Counter(term.lower() for term in [*ascii_terms, *cjk_terms] if term.lower() not in stop_words)
    tags: list[str] = []
    for candidate in [*titles, *(term for term, _ in ranked.most_common(8))]:
        compact = " ".join(candidate.split())[:20]
        if compact and compact not in tags:
            tags.append(compact)
        if len(tags) >= 5:
            break
    return "标签：" + "，".join(tags)
