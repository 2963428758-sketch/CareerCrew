"""A2 冒烟测试：校验核心包与关键依赖可导入。

测试即文档：新开发者读此文件即可知道「项目至少能在 conda env careercrew 下被导入与启动」。
"""
from __future__ import annotations

import importlib


def test_core_packages_importable() -> None:
    """核心包（ai / core / api / mcp）必须可导入。"""
    for pkg in ("careercrew_ai", "careercrew_core", "careercrew_api", "careercrew_mcp"):
        mod = importlib.import_module(pkg)
        assert mod is not None, f"{pkg} 不可导入"


def test_key_dependencies_importable() -> None:
    """A1 验收要求的关键依赖必须可导入。"""
    for dep in (
        "langgraph",
        "qdrant_client",
        "FlagEmbedding",
        "sentence_transformers",
        "requests",
        "pymupdf",
        "langchain",
        "langchain_openai",
        "pydantic",
    ):
        importlib.import_module(dep)
