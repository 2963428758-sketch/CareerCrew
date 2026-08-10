"""D1 BGE-M3 集成测试：真实模型三路输出。

模型未下载时 skip（共享目录 F:/AI_models，fresh clone 无模型）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from careercrew_ai.embedding import create_embedding
from careercrew_core.state.settings import Settings

MODEL_PATH = Path("F:/AI_models/BAAI--bge-m3/snapshots/master")


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="BGE-M3 模型未下载到 F:/AI_models")
@pytest.mark.integration
def test_bge_m3_encode_three_outputs(valid_config_data: dict) -> None:
    settings = Settings.model_validate(valid_config_data)  # provider=bge_m3_local
    emb = create_embedding(settings)
    out = emb.encode(["什么是 RAG", "LangGraph 状态机"])
    assert out.dense.shape == (2, 1024)
    assert out.sparse is not None and len(out.sparse) == 2
    # sparse token id 为 int（Milvus SPARSE_FLOAT_VECTOR 要 int key）
    assert all(isinstance(k, int) for k in out.sparse[0])
    assert out.colbert is not None and len(out.colbert) == 2
