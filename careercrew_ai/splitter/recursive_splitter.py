"""RecursiveCharacterTextSplitter 切分（D1）。Markdown 感知分隔符。"""
from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter


class RecursiveSplitter:
    """Markdown 感知的递归字符切分。"""

    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        separators: list[str] | None = None,
    ) -> None:
        if separators is None:
            # 优先按 Markdown 标题 / 段落 / 句子切，最后才按字符
            separators = [
                "\n\n## ", "\n\n### ", "\n\n#### ",
                "\n\n", "\n",
                "。", "！", "？", ". ", "! ", "? ",
                " ", "",
            ]
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators,
        )

    def split(self, text: str) -> list[str]:
        return self._splitter.split_text(text)
