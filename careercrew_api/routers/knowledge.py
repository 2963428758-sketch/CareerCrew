"""知识库路由：上传入库 / 列表 / 删除（多模态 RAG）。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError

router = APIRouter()

_MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
UPLOAD_DIR = Path("data/uploads")


@router.post("/upload")
async def upload_knowledge(
    file: UploadFile = File(...),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """上传文档入库（md/txt 走文本；PDF/图片/docx/pptx/xlsx 走 MinerU 多模态解析）。"""
    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="文件超过 50MB 限制")

    filename = file.filename or "upload"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    save_path = UPLOAD_DIR / filename
    save_path.write_bytes(content)

    try:
        result = await run_in_threadpool(rt.ingest_document, str(save_path))
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析入库失败：{e}") from e
    return {"filename": filename, **result}


@router.get("")
def list_knowledge(
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """知识库状态：总点数 + 文档列表。"""
    try:
        return rt.knowledge_status()
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.delete("/{doc_id}")
def delete_knowledge(
    doc_id: str,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """删除指定文档的全部向量点。"""
    try:
        n = rt.delete_document(doc_id)
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"deleted": n, "doc_id": doc_id}
