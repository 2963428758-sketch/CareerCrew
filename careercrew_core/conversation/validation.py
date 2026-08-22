"""附件校验纯函数模块（T3.1 §14.1）。

不依赖任何重组件（无 LangChain/psycopg 等），纯字节 + 字典运算，可独立单测。

校验维度（服务端必须全部验证，§14.1）：
- extension 白名单（小写归一化）
- MIME 白名单映射（小写归一化，且与扩展名一致）
- magic bytes / file signature（文件头签名表，无第三方依赖）
- size ≤ 25MB（MAX_ATTACHMENT_SIZE）
- 文本类（md/txt）无签名可依赖，额外做 UTF-8 可解码校验

每 turn 5 个的限制属路由层业务（依赖 thread_id 计数），不在此模块。
"""
from __future__ import annotations

# §14.1 25 MB / file
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024

# 扩展名白名单（小写、含点）
EXTENSION_WHITELIST = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt", ".png", ".jpg", ".jpeg",
}

# MIME -> 扩展名 白名单映射（键为规范小写 MIME）
MIME_TO_EXTENSION = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
}

# 扩展名 -> 期望文件头签名（magic bytes）。
# 文本类（.md/.txt）无稳定签名，靠扩展名 + MIME + UTF-8 可解码判定。
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".docx": (b"PK\x03\x04",),
    ".pptx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}


def _extension_accepts_mime(ext: str, mime: str) -> bool:
    """扩展名是否接受该 MIME（.jpg/.jpeg 同族：均接受 image/jpeg 与 image/jpg）。"""
    if mime not in MIME_TO_EXTENSION:
        return False
    if MIME_TO_EXTENSION[mime] == ext:
        return True
    # JPEG 同族特例：.jpg / .jpeg 都可配 image/jpeg、image/jpg
    if ext in (".jpg", ".jpeg") and mime in ("image/jpeg", "image/jpg"):
        return True
    return False


class AttachmentValidationError(Exception):
    """附件校验失败（扩展名/MIME/签名/大小任一不合法）。

    路由层按 detail 直接映射 422（用户可见中文提示）。
    """


def _extension_of(filename: str) -> str:
    """取扩展名（小写）；无扩展名返回空串。"""
    name = (filename or "").strip()
    if not name:
        return ""
    dot = name.rfind(".")
    if dot == -1:
        return ""
    return name[dot:].lower()


def validate_attachment(filename: str, mime: str, content_head: bytes,
                        size: int, *, content: bytes | None = None) -> dict:
    """校验单个附件，返回归一化元数据 {extension, mime}。

    :param filename: 原始文件名（含扩展名）
    :param mime: 客户端声明的 MIME（大小写不敏感）
    :param content_head: 文件头字节（至少前若干字节，用于 magic 校验）
    :param size: 文件字节数
    :param content: 完整文件内容（文本类 md/txt 的 UTF-8 校验需要全文，二进制类可省略）
    :raises AttachmentValidationError: 任一维度不合法（中文详情）
    """
    ext = _extension_of(filename)
    if not ext or ext not in EXTENSION_WHITELIST:
        allowed = " / ".join(sorted(EXTENSION_WHITELIST))
        raise AttachmentValidationError(
            f"不支持的附件格式（允许：{allowed}）"
        )

    mime_norm = (mime or "").strip().lower()
    if mime_norm not in MIME_TO_EXTENSION:
        raise AttachmentValidationError(f"不支持的附件 MIME 类型：{mime or '(空)'}")
    if not _extension_accepts_mime(ext, mime_norm):
        raise AttachmentValidationError("附件扩展名与 MIME 类型不一致")

    if size < 0 or size > MAX_ATTACHMENT_SIZE:
        raise AttachmentValidationError(
            f"附件超过 25MB 限制（{size} 字节）"
        )

    # 签名校验：有签名的类型必须匹配；文本类无签名靠可解码校验。
    signatures = _SIGNATURES.get(ext)
    if signatures is not None:
        head = content_head or b""
        if not any(head.startswith(sig) for sig in signatures):
            raise AttachmentValidationError("文件内容与扩展名不符（magic 签名校验失败）")
    else:
        # md / txt：无 magic 签名，靠全文 UTF-8 可解码兜底拒绝二进制伪装文本。
        # 必须校验完整内容（而非仅 64 字节头），否则前 64 字节之后的非法字节会被漏过。
        body = content if content is not None else (content_head or b"")
        try:
            body.decode("utf-8")
        except UnicodeDecodeError as e:
            raise AttachmentValidationError("文本附件必须为合法 UTF-8 编码") from e

    return {"extension": ext, "mime": mime_norm}
