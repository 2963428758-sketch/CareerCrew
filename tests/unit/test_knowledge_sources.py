"""知识库问答来源收敛单测：top-3 + 低相关度过滤 + 读图来源保留。"""
from __future__ import annotations

from careercrew_api.runtime import _cap_sources, _read_image_paths


def _src(doc: str, score: float) -> dict:
    return {
        "doc": doc,
        "source": f"data/uploads/{doc}.md",
        "score": score,
        "text": f"{doc} 内容",
        "image_path": "",
        "page": None,
    }


def test_cap_sources_top3_by_score() -> None:
    sources = [
        _src("a", 0.1),
        _src("b", 0.9),
        _src("c", 0.5),
        _src("d", 0.3),
        _src("e", 0.7),
    ]
    out = _cap_sources(sources)
    assert [s["doc"] for s in out] == ["b", "e", "c"]


def test_cap_sources_fewer_than_limit() -> None:
    out = _cap_sources([_src("a", 0.8), _src("b", 0.2)])
    assert [s["doc"] for s in out] == ["a", "b"]


def test_cap_sources_empty() -> None:
    assert _cap_sources([]) == []


def test_cap_sources_drops_low_score() -> None:
    """score < 0.1 的来源不展示（噪声片段）。"""
    sources = [_src("a", 0.9), _src("b", 0.03), _src("c", 0.01)]
    out = _cap_sources(sources)
    assert [s["doc"] for s in out] == ["a"]
    assert out[0]["used_image"] is False


def test_cap_sources_keeps_read_image_source() -> None:
    """被 read_image 读过的来源即使低分也保留并标记 used_image。"""
    sources = [
        {**_src("resume", 0.09), "image_path": "F:/x/pages/page_002.png"},
        {**_src("course", 0.01), "image_path": "F:/x/pages/page_001.png"},
        {**_src("other", 0.5), "image_path": ""},
    ]
    out = _cap_sources(sources, keep_paths={"f:/x/pages/page_002.png"})

    docs = [s["doc"] for s in out]
    assert "resume" in docs
    assert "course" not in docs
    assert "other" in docs
    resume = next(s for s in out if s["doc"] == "resume")
    assert resume["used_image"] is True


class _FakeIteration:
    def __init__(self, tool_calls: list[dict]) -> None:
        self.tool_calls = tool_calls


class _FakeResult:
    def __init__(self, iterations: list) -> None:
        self.iterations = iterations


def test_read_image_paths_extracts() -> None:
    result = _FakeResult([
        _FakeIteration([
            {"name": "rag_query", "args": {"query": "简历", "top_k": 3}},
            {"name": "read_image", "args": {"image_path": "F:\\x\\pages\\page_002.png"}},
        ]),
    ])
    assert _read_image_paths(result) == {"f:/x/pages/page_002.png"}
