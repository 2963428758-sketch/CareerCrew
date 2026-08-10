"""多模态 RAG MCP server（MULTIMODAL_RAG_SPEC MCP 封装）。

工具：ingest_document / search / query（检索+看图回答）/ status。
传输：默认 stdio（本地 Agent 直连）；`--http --port` 启用 Streamable HTTP
（默认绑定 127.0.0.1，v1 不加认证，README 注明）。

启动：``python -m careercrew_mcp`` 或 ``careercrew-mcp``（须用 careercrew env 的 python）。
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

_UPLOAD_DIR = Path("data/uploads")


class _Runtime:
    """进程级单例：settings / embedding / store / visual encoder / search / pipeline。"""

    def __init__(self) -> None:
        self.settings = None
        self.embedding = None
        self.store = None
        self.search = None
        self.pipeline = None
        self.llm = None
        self._ready = False

    def ensure(self):
        if self._ready:
            return
        from careercrew_ai.embedding import create_embedding
        from careercrew_ai.llm import create_llm
        from careercrew_ai.reranker.siliconflow_vl_reranker import SiliconFlowVLReranker
        from careercrew_ai.vector_store import create_vector_store
        from careercrew_core.rag.pipeline_multimodal import MultimodalIngestionPipeline
        from careercrew_core.rag.retrieval.multimodal_search import MultimodalSearch
        from careercrew_core.state.settings import load_settings
        from careercrew_core.tools.internal.read_image import make_read_image_tool

        settings = load_settings()
        embedding = create_embedding(settings)
        store = create_vector_store(settings)
        rr = SiliconFlowVLReranker(settings)
        img_reader = make_read_image_tool(settings)
        search = MultimodalSearch(
            embedding, store, reranker=rr, top_m=30,
            image_reader=lambda p: img_reader.invoke({"image_path": p}),
        )
        pipeline = MultimodalIngestionPipeline(
            embedding, store, contextual=False,
            output_dir=settings.rag.loaders.output_dir,
        )
        self.settings = settings
        self.embedding = embedding
        self.store = store
        self.search = search
        self.pipeline = pipeline
        self.llm = create_llm(settings, max_tokens=2048)
        self._ready = True


_rt = _Runtime()
mcp = FastMCP("careercrew-mm-rag")


def _bind(server: FastMCP) -> None:
    """把工具注册到指定 FastMCP 实例（HTTP 模式用自定义 host/port 时）。"""
    server.tool()(ingest_document)
    server.tool()(search)
    server.tool()(query)
    server.tool()(status)


def _parse_json(value: str, default=None):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _download(url: str) -> Path:
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = Path(urllib.parse.urlparse(url).path).name or "download"
    target = _UPLOAD_DIR / name
    urllib.request.urlretrieve(url, str(target))  # noqa: S310 - 用户显式传入 URL
    return target


@mcp.tool()
def ingest_document(path: str, metadata: str = "") -> dict:
    """入库文档（本地路径或 http(s) URL，PDF/图片/Markdown 均可），返回 doc_id 与入库点数。"""
    _rt.ensure()
    src = _download(path) if path.lower().startswith(("http://", "https://")) else Path(path)
    meta = _parse_json(metadata, {}) or {}
    if not src.exists():
        return {"error": f"文件不存在: {src}", "doc_id": "", "points": 0}
    n = _rt.pipeline.ingest_file(src, metadata=meta)
    return {"doc_id": src.stem, "points": n, "path": str(src)}


@mcp.tool()
def search(query: str, image_path: str = "", top_k: int = 5, filters: str = "") -> list[dict]:
    """混合检索：文本查询或图片查询（image_path 传本地图），返回图文命中列表。"""
    _rt.ensure()
    flt = _parse_json(filters)
    results = _rt.search.search(
        query, top_k=top_k, filters=flt, image_path=image_path or None
    )
    return [
        {
            "id": r.id,
            "score": round(float(r.score), 4),
            "text": r.text,
            "image_path": r.image_path,
            "type": r.type,
            "page": r.page,
            "doc": r.metadata.get("doc", ""),
        }
        for r in results
    ]


@mcp.tool()
def query(question: str, image_path: str = "", top_k: int = 5) -> dict:
    """检索 + VLM 看图回答：返回 {answer, sources}（sources 含 image_path 供展示）。"""
    _rt.ensure()
    from careercrew_core.rag.vlm_answer import vlm_answer

    results = _rt.search.search(question, top_k=top_k, image_path=image_path or None)
    return vlm_answer(_rt.settings, question, results, llm=_rt.llm)


@mcp.tool()
def status() -> dict:
    """库状态：各 collection 点数与配置后端。"""
    _rt.ensure()
    s = _rt.settings
    return {
        "vector_store": s.vector_store.backend,
        "url": s.vector_store.url,
        "collections": s.vector_store.collections,
        "knowledge_points": _rt.store.count(),
        "vlm_model": s.vlm.model,
        "rerank_model": s.vlm.rerank_model,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="careercrew-mcp", description="多模态 RAG MCP server")
    parser.add_argument("--http", action="store_true", help="启用 Streamable HTTP（默认 stdio）")
    parser.add_argument("--port", type=int, default=8080, help="HTTP 端口（默认 8080）")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 绑定地址（默认 127.0.0.1）")
    args = parser.parse_args()
    # 预热：langchain/transformers 等重导入在主线程完成，避免事件循环线程内 import 死锁
    from careercrew_core.rag.pipeline_multimodal import MultimodalIngestionPipeline  # noqa: F401
    from careercrew_core.rag.retrieval.multimodal_search import MultimodalSearch  # noqa: F401
    from careercrew_core.tools.internal.read_image import make_read_image_tool  # noqa: F401
    from careercrew_ai.llm import create_llm  # noqa: F401
    from careercrew_ai.vector_store import create_vector_store  # noqa: F401
    if args.http:
        server = FastMCP("careercrew-mm-rag", host=args.host, port=args.port)
        _bind(server)
        server.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
