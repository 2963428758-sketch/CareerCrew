"""处理长期记忆向量 outbox；仅执行已提交的数据库任务。"""
from __future__ import annotations

import argparse
import json
import sys

from careercrew_ai.embedding.base_embedding import create_embedding
from careercrew_ai.vector_store.qdrant_store import QdrantStore
from careercrew_core.memory import create_memory_db
from careercrew_core.memory.records import LongTermMemoryRepository
from careercrew_core.memory.vector_outbox import MemoryRecordVectorIndexer, drain_vector_outbox
from careercrew_core.state.settings import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)
    settings = load_settings()
    db = create_memory_db(settings)
    store = QdrantStore(settings, collection_name=settings.vector_store.collections["episodic_memory"])
    result = drain_vector_outbox(
        LongTermMemoryRepository(db), MemoryRecordVectorIndexer(create_embedding(settings), store),
        limit=max(1, min(args.limit, 500)),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
