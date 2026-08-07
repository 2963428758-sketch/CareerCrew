"""Contextual Chunking（D1）：LLM 给每块生成文档级上下文前置。

Anthropic Contextual Retrieval 法，减 49% 检索失败。LLM 失败则降级为普通块（不加前缀）。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from careercrew_core.rag.chunking.document_chunker import Chunk

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "careercrew_ai" / "prompts" / "contextual_chunking.txt"
)

_DEFAULT_PROMPT = (
    "<document>\n{document}\n</document>\n"
    "Here is the chunk we want to situate within the whole document:\n<chunk>\n{chunk_text}\n</chunk>\n"
    "Please give a short succinct context to situate this chunk within the overall document "
    "for the purposes of improving search retrieval of the chunk. "
    "Answer only with the succinct context and nothing else. 用中文，50-100 字。"
)


class Contextualizer:
    """给 chunk 生成文档级上下文前置（Anthropic Contextual Retrieval）。"""

    def __init__(self, llm: BaseChatModel, prompt_path: Path | None = None) -> None:
        self._llm = llm
        path = prompt_path or _PROMPT_PATH
        self._prompt_template = path.read_text(encoding="utf-8") if path.exists() else _DEFAULT_PROMPT

    def contextualize(self, chunk: Chunk, document: str) -> Chunk:
        """给 chunk 加文档级上下文前置，返回填好 contextualized_text 的 chunk。"""
        prompt = self._prompt_template.format(document=document[:3000], chunk_text=chunk.text)
        try:
            resp = self._llm.invoke(prompt)
            context = resp.content if isinstance(resp.content, str) else str(resp.content)
            context = context.strip()
        except Exception:
            context = ""  # 降级：不加前缀（对齐 DEV_SPEC 5.7）
        chunk.contextualized_text = f"{context}\n\n{chunk.text}" if context else chunk.text
        return chunk
