"""resume 路由：上传（多模态识别）+ 简历优化流式。

上传类型识别：
- 图片（png/jpg/...）-> read_image 视觉描述
- txt/md/markdown -> MarkdownLoader
- pdf/doc/docx/... -> MinerU 解析（runtime.load_document）
- >200k 字符截断标记 truncated:true
"""
from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import StreamingResponse

from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError
from careercrew_api.schemas import GenerateRequest, UploadResponse
from careercrew_api.sse import done_event, error_event, stage_event, stream_agent

router = APIRouter()

_MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20MB
_MAX_CONTENT_CHARS = 200_000
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
_TEXT_EXTS = {".txt", ".md", ".markdown"}

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads"


def _ndjson_response(gen: Generator[str, None, None]) -> StreamingResponse:
    return StreamingResponse(
        gen,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/upload", response_model=UploadResponse)
async def upload(
    file: UploadFile = File(...),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> UploadResponse:
    """上传简历文件 -> 类型识别 -> 解析为文本。

    - 图片 -> read_image 视觉描述
    - txt/md -> 直接读文本
    - pdf/doc/... -> MinerU 解析
    - >200k 字符截断
    """
    content_bytes = await file.read()
    if len(content_bytes) > _MAX_UPLOAD_SIZE:
        return UploadResponse(
            filename=file.filename or "unknown",
            doc_type="error",
            content="文件超过 20MB 限制",
        )

    # 文件名防路径穿越：只取 basename（恶意文件名可含 ../ 或盘符）
    filename = Path(file.filename or "upload").name or "upload"
    ext = Path(filename).suffix.lower()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    save_path = UPLOAD_DIR / filename
    save_path.write_bytes(content_bytes)

    if ext in _IMAGE_EXTS:
        doc_type = "image"
        try:
            text = rt.read_image(str(save_path))
        except Exception as e:
            return UploadResponse(filename=filename, doc_type="error", content=f"图片识别失败：{e}")
    elif ext in _TEXT_EXTS:
        doc_type = "text"
        text = content_bytes.decode("utf-8", errors="replace")
    else:
        doc_type = ext.lstrip(".") or "unknown"
        try:
            text = rt.load_document(str(save_path))
        except Exception as e:
            return UploadResponse(
                filename=filename, doc_type="error",
                content=f"文件解析失败（{doc_type} 格式）：{e}",
            )

    truncated = False
    if len(text) > _MAX_CONTENT_CHARS:
        text = text[:_MAX_CONTENT_CHARS]
        truncated = True

    # 清理解析产生的表格碎片（Word 排版 -> markdown 表格）
    # 逐行处理：有内容的单元格保留，空单元格和分隔行删除
    cleaned_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")]
            cells = [c for c in cells if c]  # 去掉空单元格
            if not cells:
                continue  # 全空 -> 删
            if all(set(c) <= set("-: ") for c in cells):
                continue  # 分隔行 |---|---| -> 删
            cleaned_lines.append("  ".join(cells))  # 有内容 -> 只留内容
        else:
            cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)
    # 连续空行压缩
    import re
    text = re.sub(r"\n{3,}", "\n\n", text)

    return UploadResponse(
        filename=filename,
        doc_type=doc_type,
        content=text,
        truncated=truncated,
        char_count=len(text),
    )


@router.post("/generate")
def generate(req: GenerateRequest, rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> StreamingResponse:
    """简历顾问以"上传简历 + 目标 JD"为输入流式优化。"""

    def run_fn(cb):
        from langchain_core.messages import HumanMessage

        agent = rt.new_resume_advisor(cb)
        prompt = f"我的简历：\n{req.user_resume}\n\n目标 JD：\n{req.jd or '未指定'}\n\n请帮我优化简历。"
        state = {
            "thread_id": req.thread_id, "user_id": req.user_id, "stage": "resume",
            "user_intent": prompt,
            "messages": [HumanMessage(content=prompt)],
            "pending_action": None, "agent_outputs": {}, "target_companies": [],
        }
        agent.run(state)

    def gen() -> Generator[str, None, None]:
        try:
            yield stage_event("resume")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, timeout=120.0):
                evt = json.loads(line)
                if evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            yield done_event("".join(content_parts))
        except RuntimeInitError as e:
            yield error_event(str(e))
        except Exception as e:
            yield error_event(str(e))

    return _ndjson_response(gen())
