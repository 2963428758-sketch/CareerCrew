"""附件上下文解析与消息组装（T3.2 补全：上传文件真正进入对话上下文）。

服务端按附件 id 校验所有权后读取内容，转成可注入 LLM 上下文的文本块：
- .md/.txt：直读 UTF-8 文本（截断）
- .png/.jpg/.jpeg：VLM（settings.vlm，默认 Qwen3-VL）看图描述 → 文本
- .pdf/.docx/.pptx/.xlsx：MinerU 解析（复用管线 loader）→ 页面 markdown 拼接

块形状：{"id", "filename", "kind": text|image|document|error, "content"}。
组装：``build_user_message(text, blocks)`` 把用户原话 + 附件内容拼成单条 human 消息，
避免把附件正文写进 conversation 用户消息（展示层保持原话，regenerate 靠 metadata 恢复）。
"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from careercrew_api.runtime import CareerCrewRuntime

# 单个附件注入上限（字符）；超过截断，防止上下文爆炸
_ATTACHMENT_TEXT_LIMIT = 30_000

# 每轮最多注入的附件块数（与上传 5 个/会话对齐，超出丢弃并提示）
_MAX_ATTACHMENT_BLOCKS = 5

# 附件块类型 -> 展示标签
_KIND_LABEL = {
    "text": "文本",
    "image": "图片内容",
    "document": "文档内容",
    "error": "解析状态",
}


class AttachmentRejected(Exception):
    """附件校验失败：不存在 / 越权 / 内容不可用。路由层语义=拒绝（422）。"""


def build_user_message(text: str, blocks: list[dict] | None) -> str:
    """把用户原话与附件文本块拼成注入 LLM 的 human 消息内容。

    blocks 为空时原样返回 text；否则按「原话 + [附件 N：文件名] 内容」追加，
    标题行提示模型这是用户本轮附带的上传文件。
    """
    if not blocks:
        return text
    parts = [text or "（本轮附带上传文件）"]
    for i, b in enumerate(blocks[: _MAX_ATTACHMENT_BLOCKS], start=1):
        label = _KIND_LABEL.get(b.get("kind") or "", "内容")
        parts.append(f"[附件 {i}：{b.get('filename') or '未命名'}（{label}）]\n{b.get('content') or ''}")
    return "\n\n".join(parts)


def _image_mime(image_path: str, mime_type: str | None = None) -> str:
    """返回视觉模型可识别的图片 MIME，优先使用上传时的类型。"""
    normalized = (mime_type or "").strip().lower()
    if normalized == "image/jpg":
        return "image/jpeg"
    if normalized.startswith("image/"):
        return normalized
    guessed, _ = mimetypes.guess_type(image_path)
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/png"


def describe_image(
    settings,
    image_path: str,
    prompt: str = "请详细描述这张图片的内容，并提取其中的文字。",
    mime_type: str | None = None,
) -> str:
    """用 VLM（settings.vlm）读取本地图片，返回描述文本。失败抛异常由调用方收口。"""
    import base64

    from openai import OpenAI

    p = Path(image_path)
    if not p.is_file():
        raise AttachmentRejected(f"图片不存在：{image_path}")
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    client = OpenAI(base_url=settings.vlm.base_url, api_key=settings.vlm.api_key)
    resp = client.chat.completions.create(
        model=settings.vlm.model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{_image_mime(image_path, mime_type)};base64,{b64}"},
                },
            ],
        }],
        temperature=0.3,
        max_tokens=1024,
        timeout=120,
    )
    return (resp.choices[0].message.content or "").strip()


def extract_pdf_text(path: str) -> str:
    """使用 PyMuPDF 提取 PDF 页面文本，作为 MinerU 不可用时的轻量回退。"""
    import fitz

    document = fitz.open(path)
    try:
        text = "\n\n".join(page.get_text("text") for page in document).strip()
    finally:
        document.close()
    return _truncate(text)


def _truncate(text: str) -> str:
    return text if len(text) <= _ATTACHMENT_TEXT_LIMIT else text[:_ATTACHMENT_TEXT_LIMIT] + "…"
