"""Dashboard 数据读取（L4，可测试 helper）。"""
from __future__ import annotations

from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.user_model import UserModelStore
from careercrew_core.state.settings import load_settings


def get_settings_summary() -> dict:
    s = load_settings()
    return {
        "llm": s.llm.model, "embedding": s.embedding.provider,
        "rerank": s.rerank.backend, "vector_store": s.vector_store.backend,
        "rag": s.rag.retrieval.mode,
    }


def get_user_model(user_id: str = "u_001", path: str = "data/user_model.json") -> dict:
    return UserModelStore(path).load(user_id).model_dump()


def get_episodic_entries(transcript: str = "data/transcripts/u_001/m1.jsonl") -> list[dict]:
    return [e.model_dump() for e in EpisodicMemory(transcript)._read_all()]
