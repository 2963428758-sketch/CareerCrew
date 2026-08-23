"""上传文件分块限读：避免把超大 multipart body 整体缓冲进内存（内存 DoS 防护）。

大小上限必须在「读取」阶段生效——先 `await file.read()` 全量读入再校验长度，
攻击者可用超大 body 直接打爆进程内存。
"""
from __future__ import annotations

from fastapi import UploadFile

_READ_CHUNK = 1024 * 1024


async def read_bounded(file: UploadFile, limit: int) -> bytes | None:
    """分块读取上传内容，最多读 limit 字节。

    读满 limit 后若仍有剩余（下一 chunk 非空）返回 None 表示超限；
    否则返回完整字节内容。
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)
