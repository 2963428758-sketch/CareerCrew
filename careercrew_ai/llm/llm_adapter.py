"""LLM 薄适配（A4）。

用 langchain init_chat_model（不自建 BaseLLM，ADR-4），base_url 指向硅基流动（OpenAI 兼容）。
构造不触网，首次 invoke 才调 API；api_key 校验在 A3 load_settings 已 fail-fast。

分层：careercrew_ai 最底层，Settings 仅 TYPE_CHECKING（运行时鸭子类型，避免 ai->core 反向依赖）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings


def create_llm(
    settings: Settings,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> BaseChatModel:
    """按 settings.llm 创建 ChatModel。

    model_provider="openai" -> ChatOpenAI（OpenAI 兼容）。
    api_key/model/temperature/max_tokens 可临时覆盖，否则取配置默认。
    timeout/max_retries 兜底：上游挂起时快速失败重试，而非干等到 SSE 层空闲超时。
    """
    cfg = settings.llm
    key = api_key if (api_key is not None and api_key.strip()) else cfg.api_key
    return init_chat_model(
        model=model if model is not None else cfg.model,
        model_provider=cfg.provider,
        base_url=cfg.base_url,
        api_key=key,
        temperature=temperature if temperature is not None else cfg.temperature,
        max_tokens=max_tokens if max_tokens is not None else cfg.max_tokens,
        timeout=60,
        max_retries=2,
    )
