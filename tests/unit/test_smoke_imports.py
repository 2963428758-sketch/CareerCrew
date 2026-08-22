"""A2 冒烟测试：校验核心包与关键依赖可导入。

测试即文档：新开发者读此文件即可知道「项目至少能在 conda env careercrew 下被导入与启动」。

轻量依赖集在 CI 全量跑；重 ML 栈（FlagEmbedding / sentence-transformers / torch）仅在本地
conda env 安装（DEV_SPEC §4.4），未安装时自动 skip，避免 CI 装数 GB 的 torch。
"""
from __future__ import annotations

import importlib
import importlib.util

import pytest


def test_core_packages_importable() -> None:
    """核心包（ai / core / api / mcp）必须可导入。"""
    for pkg in ("careercrew_ai", "careercrew_core", "careercrew_api", "careercrew_mcp"):
        mod = importlib.import_module(pkg)
        assert mod is not None, f"{pkg} 不可导入"


def test_key_dependencies_importable() -> None:
    """A1 验收要求的关键依赖必须可导入（轻量集，CI 覆盖）。"""
    for dep in (
        "langgraph",
        "qdrant_client",
        "requests",
        "pymupdf",
        "langchain",
        "langchain_openai",
        "pydantic",
    ):
        importlib.import_module(dep)


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


@pytest.mark.skipif(
    not _module_available("FlagEmbedding") or not _module_available("sentence_transformers"),
    reason="重 ML 栈仅本地 conda env 安装（DEV_SPEC §4.4），CI 轻量环境自动跳过",
)
def test_heavy_ml_dependencies_importable() -> None:
    """重 ML 栈（BGE-M3 / sentence-transformers）在完整环境下必须可导入。"""
    importlib.import_module("FlagEmbedding")
    importlib.import_module("sentence_transformers")
