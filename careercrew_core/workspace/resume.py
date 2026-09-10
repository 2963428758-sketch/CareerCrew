"""General resume master workspace: versions, materials, annotations and exports."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import threading
import zipfile
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any

from careercrew_core.conversation.store import ConversationStore
from careercrew_core.conversation.uuid7 import uuid7
from careercrew_core.preparation.exports import export_docx, export_pdf


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _public(row: dict | None) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


def _text(value: Any, field: str, limit: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field} 不能为空")
    if len(text) > limit:
        raise ValueError(f"{field} 不能超过 {limit} 个字符")
    return text


def _safe_filename(label: str, fallback: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", label).strip(" .") or fallback
    return name[:100]


def _safe_export_error(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "导出版本不存在或不属于当前账号"
    if isinstance(exc, ValueError):
        return "导出内容校验失败或超过大小限制"
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return "导出服务暂时不可用"
    return "导出失败，请稍后重试"


class ResumeWorkspace:
    """Owner-scoped resume workspace with a durable-PG / in-memory-test split."""

    def __init__(self, conversation_store: ConversationStore, *, pool=None) -> None:
        self.conversation_store = conversation_store
        self._db = conversation_store._db
        self._pool = pool
        if self._pool is None and hasattr(self._db, "_get_pool"):
            self._pool = self._db._get_pool()
        self._fake = self._pool is None
        self._lock = threading.RLock()
        self._masters: dict[str, dict] = {}
        self._versions: dict[str, dict] = {}
        self._materials: dict[str, dict] = {}
        self._annotations: dict[str, dict] = {}
        self._exports: dict[str, dict] = {}

    def _connect(self):
        if self._pool is None:  # pragma: no cover
            raise RuntimeError("resume workspace postgres pool is not configured")
        return self._pool.connection()

    @staticmethod
    def _row(row: Any) -> dict:
        return _public(dict(row))

    def create_master(self, owner_id: str, *, title: str, content: str,
                      description: str = "") -> dict:
        title = _text(title, "母版名称", 200, True)
        content = _text(content, "简历内容", 50000, True)
        description = _text(description, "说明", 1000)
        now = _now()
        master_id = str(uuid7())
        version_id = str(uuid7())
        if self._fake:
            self._masters[master_id] = {
                "id": master_id, "owner_id": owner_id, "title": title,
                "description": description, "created_at": now, "updated_at": now,
            }
            self._versions[version_id] = self._version_row(
                version_id, owner_id, master_id, None, "母版 v1", content, "master", now, 1,
            )
            return self._master_public(self._masters[master_id])
        with self._connect() as conn, conn.transaction():
            master = conn.execute(
                "INSERT INTO resume_master_documents "
                "(id, owner_id, title, description, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                (master_id, owner_id, title, description, now, now),
            ).fetchone()
            conn.execute(
                "INSERT INTO resume_master_versions "
                "(id, owner_id, master_id, parent_version_id, label, content, kind, version_number, content_sha256, created_at) "
                "VALUES (%s,%s,%s,NULL,%s,%s,'master',1,%s,%s)",
                (version_id, owner_id, master_id, "母版 v1", content,
                 hashlib.sha256(content.encode()).hexdigest(), now),
            )
        return self._master_public(self._row(master))

    def list_masters(self, owner_id: str) -> list[dict]:
        if self._fake:
            rows = [row for row in self._masters.values() if row["owner_id"] == owner_id]
            rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        else:
            with self._connect() as conn:
                rows = [self._row(row) for row in conn.execute(
                    "SELECT * FROM resume_master_documents WHERE owner_id=%s ORDER BY updated_at DESC, id DESC",
                    (owner_id,),
                ).fetchall()]
        return [self._master_public(row) for row in rows]

    def get_master(self, owner_id: str, master_id: str) -> dict | None:
        if self._fake:
            row = self._masters.get(master_id)
            return self._master_public(row) if row and row["owner_id"] == owner_id else None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM resume_master_documents WHERE owner_id=%s AND id=%s",
                (owner_id, master_id),
            ).fetchone()
        return self._master_public(self._row(row)) if row else None

    def list_versions(self, owner_id: str, master_id: str) -> list[dict]:
        if self.get_master(owner_id, master_id) is None:
            return []
        if self._fake:
            rows = [row for row in self._versions.values()
                    if row["owner_id"] == owner_id and row["master_id"] == master_id]
            rows.sort(key=lambda row: (int(row.get("version_number", 0)), str(row.get("created_at") or "")), reverse=True)
        else:
            with self._connect() as conn:
                rows = [self._row(row) for row in conn.execute(
                    "SELECT * FROM resume_master_versions WHERE owner_id=%s AND master_id=%s "
                    "ORDER BY version_number DESC, created_at DESC, id DESC", (owner_id, master_id),
                ).fetchall()]
        return [self._version_public(row) for row in rows]

    def _version(self, owner_id: str, version_id: str) -> dict | None:
        if self._fake:
            row = self._versions.get(version_id)
            return dict(row) if row and row["owner_id"] == owner_id else None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM resume_master_versions WHERE owner_id=%s AND id=%s",
                (owner_id, version_id),
            ).fetchone()
        return self._row(row) if row else None

    def create_version(self, owner_id: str, master_id: str, *, label: str,
                       content: str, parent_version_id: str | None = None,
                       kind: str = "derived") -> dict:
        if self.get_master(owner_id, master_id) is None:
            raise PermissionError("简历母版不存在或不属于当前账号")
        label = _text(label, "版本名称", 120, True)
        content = _text(content, "简历内容", 50000, True)
        if kind not in {"master", "derived"}:
            raise ValueError("版本类型不正确")
        if parent_version_id:
            parent = self._version(owner_id, parent_version_id)
            if parent is None or parent["master_id"] != master_id:
                raise PermissionError("父版本不存在或不属于当前母版")
        now = _now()
        version_id = str(uuid7())
        if self._fake:
            version_number = max(
                (int(row.get("version_number", 0)) for row in self._versions.values()
                 if row["owner_id"] == owner_id and row["master_id"] == master_id), default=0,
            ) + 1
            row = self._version_row(version_id, owner_id, master_id, parent_version_id,
                                    label, content, kind, now, version_number)
            self._versions[version_id] = row
            self._masters[master_id]["updated_at"] = now
            return self._version_public(row)
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                """
                INSERT INTO resume_master_versions
                    (id, owner_id, master_id, parent_version_id, label, content, kind,
                     version_number, content_sha256, created_at)
                SELECT %s,%s,%s,%s,%s,%s,%s,COALESCE(MAX(version_number),0)+1,%s,%s
                FROM resume_master_versions WHERE owner_id=%s AND master_id=%s
                RETURNING *
                """,
                (version_id, owner_id, master_id, parent_version_id, label, content, kind,
                 hashlib.sha256(content.encode()).hexdigest(), now, owner_id, master_id),
            ).fetchone()
            conn.execute(
                "UPDATE resume_master_documents SET updated_at=%s WHERE owner_id=%s AND id=%s",
                (now, owner_id, master_id),
            )
        return self._version_public(self._row(row))

    def diff_versions(self, owner_id: str, left_version_id: str,
                      right_version_id: str) -> dict | None:
        left = self._version(owner_id, left_version_id)
        right = self._version(owner_id, right_version_id)
        if left is None or right is None or left["master_id"] != right["master_id"]:
            return None
        diff = "\n".join(difflib.unified_diff(
            str(left["content"]).splitlines(), str(right["content"]).splitlines(),
            fromfile=str(left.get("label") or left_version_id),
            tofile=str(right.get("label") or right_version_id), lineterm="",
        ))
        return {
            "left_version_id": left_version_id, "right_version_id": right_version_id,
            "left_label": left.get("label"), "right_label": right.get("label"),
            "changed": str(left["content"]) != str(right["content"]),
            "changed_fields": ["content"] if str(left["content"]) != str(right["content"]) else [],
            "unified_diff": diff[:20000],
        }

    def create_material(self, owner_id: str, *, title: str, context: str = "",
                        role: str = "", actions: str = "", results: str = "",
                        tags: list[str] | None = None) -> dict:
        title = _text(title, "素材标题", 200, True)
        clean_tags = [_text(tag, "标签", 50, True) for tag in (tags or [])[:20]]
        row = {
            "id": str(uuid7()), "owner_id": owner_id, "title": title,
            "context": _text(context, "背景", 5000), "role": _text(role, "职责", 2000),
            "actions": _text(actions, "行动", 5000), "results": _text(results, "结果", 5000),
            "tags": clean_tags, "created_at": _now(), "updated_at": _now(),
        }
        if self._fake:
            self._materials[row["id"]] = row
        else:
            with self._connect() as conn, conn.transaction():
                inserted = conn.execute(
                    "INSERT INTO resume_experience_materials "
                    "(id, owner_id, title, context, role, actions, results, tags, created_at, updated_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                    (row["id"], owner_id, title, row["context"], row["role"], row["actions"],
                     row["results"], json.dumps(clean_tags, ensure_ascii=False), row["created_at"], row["updated_at"]),
                ).fetchone()
            row = self._row(inserted)
        return self._material_public(row)

    def list_materials(self, owner_id: str) -> list[dict]:
        if self._fake:
            rows = [row for row in self._materials.values() if row["owner_id"] == owner_id]
        else:
            with self._connect() as conn:
                rows = [self._row(row) for row in conn.execute(
                    "SELECT * FROM resume_experience_materials WHERE owner_id=%s ORDER BY updated_at DESC, id DESC",
                    (owner_id,),
                ).fetchall()]
        return [self._material_public(row) for row in rows]

    def create_annotation(self, owner_id: str, version_id: str, *, start_offset: int,
                          end_offset: int, note: str) -> dict:
        version = self._version(owner_id, version_id)
        if version is None:
            raise PermissionError("简历版本不存在或不属于当前账号")
        if not 0 <= start_offset <= end_offset <= len(str(version["content"])):
            raise ValueError("批注范围不合法")
        note = _text(note, "批注", 1000, True)
        row = {
            "id": str(uuid7()), "owner_id": owner_id, "version_id": version_id,
            "start_offset": start_offset, "end_offset": end_offset, "note": note,
            "status": "open", "created_at": _now(), "updated_at": _now(),
        }
        if self._fake:
            self._annotations[row["id"]] = row
        else:
            with self._connect() as conn, conn.transaction():
                inserted = conn.execute(
                    "INSERT INTO resume_annotations "
                    "(id, owner_id, version_id, start_offset, end_offset, note, status, created_at, updated_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,'open',%s,%s) RETURNING *",
                    (row["id"], owner_id, version_id, start_offset, end_offset, note, row["created_at"], row["updated_at"]),
                ).fetchone()
            row = self._row(inserted)
        return self._annotation_public(row)

    def list_annotations(self, owner_id: str, version_id: str) -> list[dict]:
        if self._version(owner_id, version_id) is None:
            return []
        if self._fake:
            rows = [row for row in self._annotations.values()
                    if row["owner_id"] == owner_id and row["version_id"] == version_id]
        else:
            with self._connect() as conn:
                rows = [self._row(row) for row in conn.execute(
                    "SELECT * FROM resume_annotations WHERE owner_id=%s AND version_id=%s "
                    "ORDER BY start_offset, created_at, id", (owner_id, version_id),
                ).fetchall()]
        return [self._annotation_public(row) for row in rows]

    def create_export_job(self, owner_id: str, version_ids: list[str], formats: list[str]) -> dict:
        if not 1 <= len(version_ids) <= 20 or len(set(version_ids)) != len(version_ids):
            raise ValueError("一次最多导出 20 个不重复版本")
        clean_formats = list(dict.fromkeys(formats))
        if not clean_formats or any(fmt not in {"pdf", "docx"} for fmt in clean_formats):
            raise ValueError("导出格式仅支持 pdf 或 docx")
        versions = [self._version(owner_id, version_id) for version_id in version_ids]
        if any(version is None for version in versions):
            raise PermissionError("简历版本不存在或不属于当前账号")
        if sum(len(str(version["content"])) for version in versions if version) > 500000:
            raise ValueError("批量导出内容不能超过 500000 个字符")
        now = _now()
        row = {
            "id": str(uuid7()), "owner_id": owner_id, "version_ids": version_ids,
            "formats": clean_formats, "status": "queued", "error": None,
            "result_zip": None, "expires_at": None, "created_at": now, "updated_at": now,
        }
        if self._fake:
            self._exports[row["id"]] = row
        else:
            with self._connect() as conn, conn.transaction():
                inserted = conn.execute(
                    "INSERT INTO resume_export_jobs "
                    "(id, owner_id, version_ids, formats, status, created_at, updated_at) "
                    "VALUES (%s,%s,%s,%s,'queued',%s,%s) RETURNING *",
                    (row["id"], owner_id, json.dumps(version_ids), json.dumps(clean_formats), now, now),
                ).fetchone()
            row = self._row(inserted)
        return self._export_public(row)

    def _export(self, owner_id: str, job_id: str) -> dict | None:
        if self._fake:
            row = self._exports.get(job_id)
            return dict(row) if row and row["owner_id"] == owner_id else None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM resume_export_jobs WHERE owner_id=%s AND id=%s", (owner_id, job_id)
            ).fetchone()
        return self._row(row) if row else None

    def run_export_job(self, owner_id: str, job_id: str) -> dict | None:
        row = self._export(owner_id, job_id)
        if row is None:
            return None
        try:
            version_ids = row.get("version_ids")
            formats = row.get("formats")
            if isinstance(version_ids, str):
                version_ids = json.loads(version_ids)
            if isinstance(formats, str):
                formats = json.loads(formats)
            versions = [self._version(owner_id, version_id) for version_id in version_ids or []]
            if any(version is None for version in versions):
                raise PermissionError("导出版本不存在或不属于当前账号")
            output = BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for version in versions:
                    label = _safe_filename(str(version.get("label") or "简历"), "resume")
                    for fmt in formats or []:
                        body = export_pdf(label, str(version["content"])) if fmt == "pdf" else export_docx(label, str(version["content"]))
                        archive.writestr(f"{label}-{str(version['id'])[:8]}.{fmt}", body)
            blob = output.getvalue()
            if len(blob) > 10 * 1024 * 1024:
                raise ValueError("导出文件超过 10MB 限制")
            row.update({"status": "done", "result_zip": blob,
                        "expires_at": (datetime.now().astimezone() + timedelta(hours=1)).isoformat(),
                        "updated_at": _now(), "error": None})
        except Exception as exc:  # keep only a user-safe category, never raw diagnostics
            row.update({"status": "failed", "error": _safe_export_error(exc), "updated_at": _now()})
        if self._fake:
            self._exports[job_id] = row
        else:
            with self._connect() as conn, conn.transaction():
                conn.execute(
                    "UPDATE resume_export_jobs SET status=%s, result_zip=%s, expires_at=%s, "
                    "error=%s, updated_at=%s WHERE owner_id=%s AND id=%s",
                    (row["status"], row.get("result_zip"), row.get("expires_at"), row.get("error"),
                     row["updated_at"], owner_id, job_id),
                )
        return self._export_public(row)

    def list_export_jobs(self, owner_id: str) -> list[dict]:
        if self._fake:
            rows = [row for row in self._exports.values() if row["owner_id"] == owner_id]
        else:
            with self._connect() as conn:
                rows = [self._row(row) for row in conn.execute(
                    "SELECT * FROM resume_export_jobs WHERE owner_id=%s ORDER BY created_at DESC, id DESC",
                    (owner_id,),
                ).fetchall()]
        return [self._export_public(row) for row in rows]

    def download_export(self, owner_id: str, job_id: str) -> bytes:
        row = self._export(owner_id, job_id)
        if row is None:
            raise PermissionError("导出任务不存在或不属于当前账号")
        if row.get("status") != "done" or not row.get("result_zip"):
            raise ValueError("导出任务尚未完成")
        expires_at = row.get("expires_at")
        if expires_at and datetime.fromisoformat(str(expires_at)) < datetime.now().astimezone():
            raise ValueError("导出文件已过期")
        return bytes(row["result_zip"])

    @staticmethod
    def _version_row(version_id, owner_id, master_id, parent_version_id, label,
                     content, kind, created_at, version_number) -> dict:
        return {
            "id": version_id, "owner_id": owner_id, "master_id": master_id,
            "parent_version_id": parent_version_id, "label": label, "content": content,
            "kind": kind, "version_number": version_number,
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "created_at": created_at,
        }

    @staticmethod
    def _master_public(row: dict | None) -> dict | None:
        if row is None:
            return None
        result = _public(row) or {}
        result.pop("owner_id", None)
        return result

    @staticmethod
    def _version_public(row: dict | None) -> dict | None:
        if row is None:
            return None
        result = _public(row) or {}
        result.pop("owner_id", None)
        return result

    @staticmethod
    def _material_public(row: dict) -> dict:
        result = _public(row) or {}
        result.pop("owner_id", None)
        tags = result.get("tags")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = []
        result["tags"] = tags or []
        return result

    @staticmethod
    def _annotation_public(row: dict) -> dict:
        result = _public(row) or {}
        result.pop("owner_id", None)
        return result

    @staticmethod
    def _export_public(row: dict) -> dict:
        result = _public(row) or {}
        result.pop("owner_id", None)
        result.pop("result_zip", None)
        for key in ("version_ids", "formats"):
            value = result.get(key)
            if isinstance(value, str):
                try:
                    result[key] = json.loads(value)
                except json.JSONDecodeError:
                    result[key] = []
        return result
