"""MinerU 本地子进程解析 loader（R2/R6）。

以独立子进程跑 `mineru -b pipeline`（模型不占本进程显存），
产物落盘到 ``output_dir/<doc_id>/``：
- ``<stem>.md`` + ``<stem>_content_list.json``：页面文本 / 对象块
- ``images/``：MinerU 裁剪图（对象块）
- ``pages/page_NNN.png``：pymupdf 渲染的整页图（ColPali 视觉路用）

解析失败抛 ``ParsingError``（调用方记 doc_type=error 跳过，不中断批量入库）。

云端 API 版本见 ``mineru_api_loader.py``（provider=api 时使用）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from careercrew_core.rag.loaders.mineru_common import (
    ParsingError,
    build_parsed_document,
    sanitize_doc_id,
)

__all__ = ["MinerULoader", "ParsingError"]


class MinerULoader:
    """MinerU 子进程解析：PDF/图片/docx/pptx/xlsx -> 页面 + 对象。"""

    def __init__(
        self,
        output_dir: str | Path,
        device: str = "cpu",
        method: str = "auto",
        formula: bool = True,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._device = device
        self._method = method if method in ("auto", "txt", "ocr") else "auto"
        self._formula = formula
        self._exe = self._find_exe()

    @staticmethod
    def _find_exe() -> str:
        """优先用当前 Python 环境的 Scripts/mineru(.exe)，回退 PATH。"""
        env_root = Path(sys.executable).parent
        scripts = env_root / "Scripts"
        for name in ("mineru.exe", "mineru"):
            for base in (scripts, env_root):
                p = base / name
                if p.exists():
                    return str(p)
        return "mineru"

    def parse(self, path: str | Path) -> ParsedDocument:
        src = Path(path)
        doc_id = sanitize_doc_id(src.stem)
        out_root = self._output_dir / doc_id
        out_root.mkdir(parents=True, exist_ok=True)

        env = dict(os.environ)
        if self._device and self._device != "auto":
            env["MINERU_DEVICE_MODE"] = self._device
        if self._device == "cuda":
            # 8GB 显存缓解碎片化 OOM（MinerU 多模型叠加时有效）
            env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        try:
            proc = subprocess.run(
                [
                    self._exe, "-p", str(src), "-o", str(out_root),
                    "-b", "pipeline", "-m", self._method,
                    "-f", str(self._formula).lower(), "-l", "ch",
                ],
                capture_output=True, text=True, timeout=1800, env=env,
                encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired as e:
            raise ParsingError(f"MinerU 解析超时: {src}") from e
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-500:]
            raise ParsingError(f"MinerU 解析失败 ({src}): {tail}")

        # MinerU 产物位于 out_root/<stem>/auto/
        auto_dir = out_root / doc_id / "auto"
        if not auto_dir.exists():
            cands = [p for p in out_root.rglob("auto") if p.is_dir()]
            auto_dir = cands[0] if cands else out_root

        return build_parsed_document(doc_id, src, out_root, auto_dir)
