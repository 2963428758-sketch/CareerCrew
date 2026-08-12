"""LLM 记忆路由（Claude Code 式）：从语义事实清单里选 top-N 最相关条目。

不做向量检索——事实量小、价值密度高，用 LLM 按描述一次选 ≤N 条更省更准。
LLM 缺失/失败时回退关键词重合打分（不阻塞主链路）。
"""
from __future__ import annotations

import json

from careercrew_core.memory.types import SemanticFact


def _fallback_score(query: str, fact: SemanticFact) -> float:
    q = query.lower()
    text = f"{fact.name} {fact.description} {json.dumps(fact.content, ensure_ascii=False)}".lower()
    hits = sum(1 for tok in q.split() if len(tok) >= 2 and tok in text)
    return hits


class MemoryRouter:
    def __init__(self, llm=None, top_n: int = 5) -> None:
        self._llm = llm
        self.top_n = max(1, top_n)

    def select(self, query: str, facts: list[SemanticFact]) -> list[SemanticFact]:
        """从 facts 里选最多 top_n 条（LLM 路由，失败回退关键词）。"""
        if not facts:
            return []
        if self._llm is None:
            return self._fallback(query, facts)
        try:
            return self._llm_select(query, facts)
        except Exception:
            return self._fallback(query, facts)

    def _manifest(self, facts: list[SemanticFact]) -> str:
        lines = []
        for i, f in enumerate(facts):
            lines.append(
                f"{i}. [{f.type}] {f.name} (modified {f.modified_at[:10]}): {f.description}"
            )
        return "\n".join(lines)

    def _llm_select(self, query: str, facts: list[SemanticFact]) -> list[SemanticFact]:
        prompt = (
            "从以下用户记忆清单里选出与查询最相关的记忆条目，最多 "
            f"{self.top_n} 条。只输出 JSON 数组（条目序号），如 [0, 3]。\n"
            f"查询：{query}\n\n记忆清单：\n{self._manifest(facts)}"
        )
        resp = self._llm.invoke(prompt)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        start = content.find("[")
        end = content.rfind("]")
        if start == -1 or end == -1:
            return self._fallback(query, facts)
        idxs = [int(x) for x in json.loads(content[start : end + 1])]
        picked = []
        for i in idxs:
            if 0 <= i < len(facts) and facts[i] not in picked:
                picked.append(facts[i])
            if len(picked) >= self.top_n:
                break
        return picked or self._fallback(query, facts)

    def _fallback(self, query: str, facts: list[SemanticFact]) -> list[SemanticFact]:
        scored = sorted(facts, key=lambda f: _fallback_score(query, f), reverse=True)
        return [f for f in scored if _fallback_score(query, f) > 0][: self.top_n]
