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
            "model_path": "./data/ms_cache/models/BAAI--bge-m3/snapshots/master",
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
            "backend": "milvus_lite",
            "persist_path": "./data/db/milvus",
            "collections": {"knowledge": "careercrew_kb", "episodic_memory": "careercrew_episodic"},
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
        "observability": {"enabled": True, "log_file": "./logs/traces.jsonl"},
        "dashboard": {"enabled": True, "port": 8501, "traces_dir": "./logs"},
    }


@pytest.fixture
def valid_config_data() -> dict:
    """字段完整的合法配置 dict（可安全 mutate）。"""
    return valid_config()


@pytest.fixture
def valid_settings() -> Settings:
    """合法 Settings 实例（单测复用）。"""
    return Settings.model_validate(valid_config())
