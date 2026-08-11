"""共享测试 fixtures。

valid_config() 返回字段完整的合法配置 dict（每次新构造，可安全 mutate）。
valid_settings / valid_config_data fixture 供需要配置的单测复用。
"""
from __future__ import annotations

import pytest

from careercrew_core.state.settings import Settings


def valid_config() -> dict:
    """字段完整的合法配置（api_key 用字面量，不依赖环境变量；结构与 config/settings.yaml 对齐）。"""
    return {
        "llm": {
            "provider": "openai",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": "sk-test-literal",
            "temperature": 0.3,
            "max_tokens": 2048,
        },
        "embedding": {
            "provider": "bge_m3_local",
            "model": "BAAI/bge-m3",
            "model_path": "F:/AI_models/BAAI--bge-m3/snapshots/master",
            "use_fp16": False,
            "batch_size": 12,
        },
        "rerank": {
            "backend": "siliconflow",
            "model": "BAAI/bge-reranker-v2-m3",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": "sk-test-literal",
            "top_m": 30,
        },
        "vector_store": {
            "backend": "qdrant",
            "url": ":memory:",
            "api_key": "",
            "collections": {"knowledge": "careercrew_mm", "episodic_memory": "careercrew_episodic"},
        },
        "rag": {
            "retrieval": {
                "mode": "hybrid",
                "fusion_algorithm": "rrf",
                "top_k_dense": 20,
                "top_k_sparse": 20,
                "top_k_final": 10,
            },
            "chunking": {
                "strategy": "recursive",
                "chunk_size": 800,
                "chunk_overlap": 100,
                "contextual": True,
            },
            "loaders": {
                "backend": "mineru",
                "provider": "local",  # 单测不依赖云端 key，走本地子进程路由
                "api_key": "",
                "model_version": "vlm",
                "poll_interval": 5,
                "timeout": 1800,
                "output_dir": "./data/parsed",
                "device": "cpu",
                "method": "auto",
                "formula": True,
                "table": True,
                "language": "ch",
            },
        },
        "vlm": {
            "model": "Qwen/Qwen3-VL-8B-Instruct",
            "rerank_model": "Qwen/Qwen3-VL-Reranker-8B",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": "sk-test-literal",
        },
        "supervisor": {
            "checkpointer": {"backend": "sqlite", "path": "./data/db/checkpointer.db"},
            "max_consecutive_agent_turns": 10,
        },
        "memory": {
            "episodic": {"transcript_dir": "./data/transcripts", "vectorize": True},
            "user_model": {"path": "./data/user_model.json"},
            "compaction": {"enabled": True, "token_threshold_ratio": 0.7, "retention_tokens": 20000},
        },
        "tools": {
            "registry": {"internal": ["rag_query", "memory_search"], "mcp": ["mcp_jobs"]},
            "hitl": {"requires_confirmation": ["submit_application", "accept_offer"]},
        },
        "hitl": {"default_policy": "confirm"},
        "langsmith": {
            "enabled": True,
            "project": "careercrew",
            "api_key": "lsv2-test-literal",
            "masking": True,
            "max_chars": 2000,
        },
    }


@pytest.fixture
def valid_config_data() -> dict:
    """字段完整的合法配置 dict（可安全 mutate）。"""
    return valid_config()


@pytest.fixture
def valid_settings() -> Settings:
    """合法 Settings 实例（单测复用）。"""
    return Settings.model_validate(valid_config())
