"""评估 runner 指标函数单元测试。"""
from __future__ import annotations

from scripts.eval_runner import citation_coverage, hit_at_k, mrr, route_accuracy, tool_success


def test_hit_at_k():
    assert hit_at_k([["d1", "d2"], ["d3"]], [["d2"], ["d3"]]) == 1.0
    assert hit_at_k([["d1", "d2"]], [["d9"]]) == 0.0


def test_mrr():
    assert mrr([["d1", "d2"], ["d9"]], [["d2"], ["d9"]]) == 0.75
    assert mrr([["d1"]], [["d9"]]) == 0.0


def test_citation_coverage():
    assert citation_coverage("答案A和B。", ["答案A", "B"]) == 1.0
    assert citation_coverage("只有答案A。", ["答案A", "缺失"]) == 0.5
    assert citation_coverage("空", []) == 1.0


def test_route_accuracy():
    assert route_accuracy(["a", "b", "c"], ["a", "x", "c"]) == 2 / 3
    assert route_accuracy([], []) == 1.0


def test_tool_success():
    assert tool_success([["search_jobs", "rag_query"]], [["search_jobs"]]) == 1.0
    assert tool_success([["rag_query"]], [["search_jobs"]]) == 0.0
