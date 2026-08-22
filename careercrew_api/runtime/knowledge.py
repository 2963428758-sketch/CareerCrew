
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:

    pass


pass





class KnowledgeDocsMixin:
    """文档摄取/知识库管理/上下文资源/mentions 解析。"""

    def read_image(self, path: str) -> str:
        """用视觉模型读图片内容。"""
        self._ensure_heavy()
        from careercrew_core.tools.internal.read_image import make_read_image_tool

        tool = make_read_image_tool(self.settings)
        return tool.invoke({"image_path": path, "prompt": "请描述图片内容并提取其中的文字。"})

    def load_document(self, path: str, output_dir: str | None = None) -> str:
        """MinerU 解析为文本（resume 上传 pdf/docx 等；按 provider 走云端 API 或本地子进程）。

        output_dir：按用户/文档隔离的解析产物目录（默认取 settings.rag.loaders.output_dir）。
        """
        loaders = self.settings.rag.loaders
        out_dir = loaders.output_dir if output_dir is None else output_dir
        if loaders.provider == "local":
            from careercrew_core.rag.loaders.mineru_loader import MinerULoader

            parsed = MinerULoader(
                out_dir,
                device=loaders.device,
                method=loaders.method,
                formula=loaders.formula,
            ).parse(path)
        else:
            from careercrew_core.rag.loaders.mineru_api_loader import MinerUApiLoader

            parsed = MinerUApiLoader(
                out_dir,
                api_key=loaders.api_key,
                model_version=loaders.model_version,
                formula=loaders.formula,
                table=loaders.table,
                language=loaders.language,
                poll_interval=loaders.poll_interval,
                timeout=loaders.timeout,
            ).parse(path)
        return parsed.to_text()

    def ingest_document(
        self,
        path: str,
        user_id: str,
        metadata: dict | None = None,
        progress_cb: Callable[[str, float], None] | None = None,
        category: str = "",
        output_dir: str | None = None,
        doc_name: str = "",
        visibility: str = "private",
    ) -> dict:
        """知识库入库（多模态管线：md 走文本，PDF/图片走 MinerU）。

        progress_cb(stage, progress) 可选进度回调：stage ∈ parse/vectorize/store，
        progress ∈ [0, 1]（阶段边界处的真实进度，非秒级平滑值）。
        category: 内容分类（resume/knowledge/interview）；空串按 doc_name（原文件名）自动识别。
        output_dir: 按用户/文档隔离的解析产物目录。
        visibility: private | public（公共仅管理员上传时指定）。
        """
        self._ensure_heavy()
        from pathlib import Path

        from careercrew_api.storage import DATA_ROOT

        p = Path(path).resolve()
        if not p.is_relative_to(DATA_ROOT.resolve()):
            raise ValueError(f"入库路径越界: {p} 不在 {DATA_ROOT} 内")
        if not category:
            from careercrew_core.rag.categories import category_for_doc

            category = category_for_doc(doc_name or p.stem)
        if visibility not in ("private", "public"):
            raise ValueError(f"invalid visibility: {visibility}")
        owner_metadata = {**(metadata or {}), "owner_user_id": user_id, "visibility": visibility}
        n = self.ingest_pipeline.ingest_file(
            p, metadata=owner_metadata, progress_cb=progress_cb, category=category,
            output_dir=output_dir,
        )
        return {"doc_id": p.stem, "points": n, "path": str(p)}

    def delete_document(self, user_id: str, doc_id: str, is_admin: bool = False) -> tuple[int, bool]:
        """删除知识文档向量点。返回 (deleted, public_blocked)。

        非 admin 只能删本人私有；admin 可额外删除公共条目。
        """
        self._ensure_heavy()
        visible = self.store.list_docs(filters={"__access_user": user_id, "doc": doc_id})
        if not visible:
            return 0, False
        has_public = any(d.get("visibility") == "public" for d in visible)
        if has_public and not is_admin:
            return 0, True
        deleted = self.store.delete_by_metadata(
            {"owner_user_id": user_id, "doc": doc_id, "visibility": "private"}
        )
        if has_public and is_admin:
            deleted += self.store.delete_by_metadata({"doc": doc_id, "visibility": "public"})
        return deleted, False

    def publish_document(self, user_id: str, doc_id: str) -> int:
        self._ensure_heavy()
        return self.store.set_payload_by_filter(
            {"visibility": "public"}, {"owner_user_id": user_id, "doc": doc_id}
        )

    def unpublish_document(self, user_id: str, doc_id: str) -> int:
        self._ensure_heavy()
        return self.store.set_payload_by_filter(
            {"visibility": "private"}, {"owner_user_id": user_id, "doc": doc_id}
        )

    def knowledge_status(self, user_id: str, scope: str = "all") -> dict:
        """知识库状态：总点数 + 文档列表。scope: all（公共+本人私有）/public/private。"""
        self._ensure_heavy()
        docs = self.store.list_docs(filters=self._knowledge_scope_filters(user_id, scope))
        return {"points": sum(int(doc.get("points", 0)) for doc in docs), "docs": docs}

    @staticmethod
    def _knowledge_scope_filters(user_id: str, scope: str) -> dict:
        if scope == "public":
            return {"visibility": "public"}
        if scope == "private":
            return {"owner_user_id": user_id}
        return {"__access_user": user_id}

    def knowledge_asset_owned(self, user_id: str, path: str) -> bool:
        """Verify an image source is visible to this tenant (own private or public)."""
        self._ensure_heavy()
        from careercrew_api.storage import DATA_ROOT

        resolved = Path(path).resolve()
        if not resolved.is_relative_to(DATA_ROOT.resolve()):
            return False
        return bool(self.store.metadata_exists({"__access_user": user_id, "image_path": str(resolved)}))

    # ── Context @ 引用（T3.4 §15）──

    def _resume_library_items(self, user_id: str) -> list[dict]:
        """读取本人简历库条目元数据（data/parsed/resumes/{user_id}/*/meta.json）。"""
        import json as _json

        from careercrew_api.storage import L

        user_dir = L.parsed_resumes / user_id
        items: list[dict] = []
        if user_dir.exists():
            for meta_path in user_dir.glob("*/meta.json"):
                try:
                    meta = _json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001 - 元数据损坏时跳过单条
                    continue
                if meta.get("user_id") != user_id:
                    continue
                items.append(meta)
        items.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return items

    def list_context_resources(self, user_id: str, types: list[str] | None = None,
                               q: str = "") -> list[dict]:
        """§15.1：返回当前用户可引用的资源（本人 private + public 知识 + 本人简历）。

        types 过滤（knowledge/resume，缺省两者）；q 按名称模糊过滤（不区分大小写）。
        返回 §15.1 形状：{"type","id","name","visibility"}。
        """
        self._ensure_heavy()
        ql = (q or "").strip().lower()
        want_knowledge = types is None or "knowledge" in types
        want_resume = types is None or "resume" in types
        items: list[dict] = []

        if want_knowledge:
            # 本人 private + public（与 ask 的 all scope 一致）
            docs = self.store.list_docs(filters=self._knowledge_scope_filters(user_id, "all"))
            for d in docs:
                doc_id = str(d.get("doc") or "")
                if ql and ql not in doc_id.lower():
                    continue
                items.append({
                    "type": "knowledge_document",
                    "id": doc_id,
                    "name": doc_id,
                    "visibility": str(d.get("visibility") or "private"),
                })

        if want_resume:
            for meta in self._resume_library_items(user_id):
                rid = str(meta.get("resume_id") or "")
                name = str(meta.get("filename") or rid)
                if ql and ql not in name.lower() and ql not in rid.lower():
                    continue
                items.append({
                    "type": "resume",
                    "id": rid,
                    "name": name,
                    "visibility": "private",
                })
        return items

    def resolve_mentions(self, user_id: str, mentions: list[dict]) -> list[dict]:
        """服务端再次校验 mentions（§15.2）；不合法抛 MentionRejected。返回 resolved dict 列表。"""
        from careercrew_api.mentions import resolve_mentions as _resolve

        self._ensure_heavy()
        docs = self.store.list_docs(filters=self._knowledge_scope_filters(user_id, "all"))
        resumes = self._resume_library_items(user_id)
        resolved = _resolve(
            user_id, mentions, knowledge_docs=docs, resume_items=resumes,
        )
        return [m.as_dict() for m in resolved]

    # ── 附件上下文（T3.2：上传文件注入对话）──

    def resolve_attachment_blocks(self, user_id: str, refs: list[dict]) -> list[dict]:
        """按附件 id 校验所有权并读取内容，返回可注入 LLM 上下文的文本块列表。

        refs: [{"id": ...}]；任一不存在/越权 → AttachmentRejected（整体拒绝，同 mentions）。
        块形状：{"id", "filename", "kind": text|image|document|error, "content"}。
        - md/txt 直读；图片走 VLM（settings.vlm）；pdf/docx/pptx/xlsx 走 MinerU 解析。
        - 单附件解析失败不阻断整体：降级为 error 块，让模型知晓该附件不可用。
        """
        from careercrew_api.attachment_context import (
            AttachmentRejected,
            _truncate,
            describe_image,
            extract_pdf_text,
        )
        from careercrew_api.storage import L
        from careercrew_api.storage import resolve_under as _storage_resolve_under

        self._ensure_heavy()
        blocks: list[dict] = []
        for ref in refs or []:
            aid = str(ref.get("id") or "")
            if not aid:
                raise AttachmentRejected("附件缺少 id")
            try:
                row = self.attachment_store.get(user_id, aid)
            except Exception as e:
                raise AttachmentRejected(f"附件不存在或无权访问：{aid}") from e
            disk_path = _storage_resolve_under(
                L.attachments, row["user_id"], row["thread_id"], aid
            )
            if not disk_path.is_file():
                raise AttachmentRejected(f"附件文件已不存在：{row.get('original_filename')}")
            filename = row.get("original_filename") or aid
            ext = Path(filename).suffix.lower()
            try:
                if ext in (".md", ".markdown", ".txt"):
                    content = _truncate(disk_path.read_text(encoding="utf-8"))
                    blocks.append({"id": aid, "filename": filename, "kind": "text", "content": content})
                elif ext in (".png", ".jpg", ".jpeg"):
                    content = _truncate(
                        describe_image(
                            self.settings,
                            str(disk_path),
                            mime_type=row.get("mime_type"),
                        )
                    )
                    blocks.append({"id": aid, "filename": filename, "kind": "image", "content": content})
                elif ext == ".pdf":
                    try:
                        output_dir = _storage_resolve_under(L.parsed_knowledge, user_id, aid)
                        content = _truncate(
                            self.extract_document_text(str(disk_path), str(output_dir))
                        )
                        if not content.strip():
                            content = extract_pdf_text(str(disk_path))
                    except Exception as mineru_error:
                        try:
                            content = extract_pdf_text(str(disk_path))
                        except Exception as fallback_error:
                            raise RuntimeError(
                                f"MinerU 解析失败：{mineru_error}；PDF 文本回退失败：{fallback_error}"
                            ) from fallback_error
                    blocks.append({"id": aid, "filename": filename, "kind": "document", "content": content})
                elif ext in (".docx", ".pptx", ".xlsx"):
                    output_dir = _storage_resolve_under(L.parsed_knowledge, user_id, aid)
                    content = _truncate(self.extract_document_text(str(disk_path), str(output_dir)))
                    blocks.append({"id": aid, "filename": filename, "kind": "document", "content": content})
                else:
                    blocks.append({
                        "id": aid, "filename": filename, "kind": "error",
                        "content": f"不支持的附件类型：{ext or '（无扩展名）'}",
                    })
            except AttachmentRejected:
                raise
            except Exception as e:  # noqa: BLE001 - 单附件解析失败降级 error 块
                blocks.append({
                    "id": aid, "filename": filename, "kind": "error",
                    "content": f"解析失败：{type(e).__name__}: {e}",
                })
        return blocks

    def extract_document_text(self, path: str, output_dir: str) -> str:
        """MinerU 解析二进制文档（仅解析不向量化），返回页面 markdown 拼接文本。"""
        parsed = self.ingest_pipeline.parse_file(path, output_dir=output_dir)
        return "\n\n".join(pg.markdown for pg in parsed.pages)

    def _resume_text(self, user_id: str, resume_id: str) -> str | None:
        """读取本人简历库条目的解析文本（data/parsed/resumes/{user_id}/{resume_id}/content.txt）。"""
        from careercrew_api.attachment_context import _truncate
        from careercrew_api.storage import L

        p = L.parsed_resumes / user_id / (resume_id or "") / "content.txt"
        if not p.is_file():
            return None
        try:
            return _truncate(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 单条读取失败视为不可用
            return None

    def _mention_knowledge_ids(self, mentions: list[dict] | None) -> list[str]:
        """mentions 中 knowledge_document 类型的 id 列表（强制检索上下文）。"""
        return [
            str(m.get("id") or "") for m in (mentions or [])
            if m.get("type") == "knowledge_document" and m.get("id")
        ]

    def _mention_blocks(self, user_id: str, mentions: list[dict] | None) -> list[dict]:
        """resume 类 mentions → 简历解析文本块（knowledge 文档走强制检索，不进消息体）。"""
        blocks: list[dict] = []
        for m in mentions or []:
            if m.get("type") != "resume":
                continue
            text = self._resume_text(user_id, str(m.get("id") or ""))
            if text:
                blocks.append({
                    "id": str(m.get("id") or ""),
                    "filename": str(m.get("name") or "简历"),
                    "kind": "text",
                    "content": text,
                })
        return blocks
