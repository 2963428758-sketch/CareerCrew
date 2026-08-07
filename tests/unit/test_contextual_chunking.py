"""D1 切分 + Contextual Chunking 单元测试（mock LLM）。"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from careercrew_core.rag.chunking.contextualizer import Contextualizer
from careercrew_core.rag.chunking.document_chunker import Chunk, DocumentChunker


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def invoke(self, prompt):
        return AIMessage(content=self.response)


def test_document_chunker_splits_and_tags_metadata() -> None:
    dc = DocumentChunker(chunk_size=30, chunk_overlap=5)
    text = "这是第一段内容。这是第二段内容。这是第三段内容。"
    chunks = dc.chunk(text, source="note.md", metadata={"topic": "rag"})
    assert len(chunks) >= 1
    assert all(c.id.startswith("c_") for c in chunks)
    assert chunks[0].metadata["source"] == "note.md"
    assert chunks[0].metadata["topic"] == "rag"


def test_contextualizer_adds_context_prefix() -> None:
    llm = FakeLLM("此块讲述 RAG 检索流程")
    ctx = Contextualizer(llm)
    chunk = Chunk(id="c_0", text="原始块内容", metadata={})
    out = ctx.contextualize(chunk, "整个文档内容...")
    assert "此块讲述 RAG 检索流程" in out.contextualized_text
    assert "原始块内容" in out.contextualized_text


def test_contextualizer_degrades_on_llm_error() -> None:
    class ErrLLM:
        def invoke(self, prompt):
            raise RuntimeError("LLM 挂了")

    ctx = Contextualizer(ErrLLM())
    chunk = Chunk(id="c_0", text="原始内容", metadata={})
    out = ctx.contextualize(chunk, "doc")
    assert out.contextualized_text == "原始内容"  # 降级：不加前缀


def test_contextualizer_uses_prompt_file() -> None:
    # prompt 文件存在（careercrew_ai/prompts/contextual_chunking.txt）
    llm = FakeLLM("上下文")
    ctx = Contextualizer(llm)
    assert "{document}" not in ctx._prompt_template or "{chunk_text}" in ctx._prompt_template
