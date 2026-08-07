"""D3 SiliconFlow rerank 集成测试：真实 API。需 SILICONFLOW_API_KEY。"""
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv()


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("SILICONFLOW_API_KEY"), reason="需 SILICONFLOW_API_KEY")
def test_siliconflow_reranker_real() -> None:
    from careercrew_ai.reranker import create_reranker
    from careercrew_ai.vector_store import QueryResult
    from careercrew_core.state.settings import load_settings

    settings = load_settings()
    rr = create_reranker(settings)
    cands = [
        QueryResult(id="0", score=0.0, text="今天天气不错", metadata={}),
        QueryResult(id="1", score=0.0, text="RAG 是检索增强生成，能减少幻觉", metadata={}),
        QueryResult(id="2", score=0.0, text="Java 后端开发，Spring Boot", metadata={}),
    ]
    out = rr.rerank("什么是 RAG", cands, top_k=2)
    assert len(out) == 2
    assert out[0].id == "1"  # RAG 文档最相关
    assert out[0].score > out[1].score
