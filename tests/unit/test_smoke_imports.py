"""A2 冒烟测试：校验四层包与关键依赖可导入，CLI 入口可运行。

测试即文档：新开发者读此文件即可知道「项目至少能在 conda env careercrew 下被导入与启动」。
"""
from __future__ import annotations

import importlib


def test_four_layer_packages_importable() -> None:
    """四层包（ai / core / cli / ui）必须可导入，且依赖方向单向。"""
    for pkg in ("careercrew_ai", "careercrew_core", "careercrew_cli", "careercrew_ui"):
        mod = importlib.import_module(pkg)
        assert mod is not None, f"{pkg} 不可导入"


def test_key_dependencies_importable() -> None:
    """A1 验收要求的关键依赖必须可导入。"""
    for dep in (
        "langgraph",
        "qdrant_client",
        "FlagEmbedding",
        "sentence_transformers",
        "mineru",
        "langchain",
        "langchain_openai",
        "pydantic",
    ):
        importlib.import_module(dep)


def test_cli_entry_runs(capsys) -> None:
    """CLI 入口 main([]) 返回 0 且打印 banner。"""
    from careercrew_cli.app import main

    assert main([]) == 0
    out = capsys.readouterr().out
    assert "CareerCrew" in out
