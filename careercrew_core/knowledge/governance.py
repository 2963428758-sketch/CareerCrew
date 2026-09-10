"""Relational governance for knowledge documents and indexed versions.

The existing Qdrant upload pipeline remains the compatibility ingestion path.
This service owns the durable logical-document/version/chunk lifecycle so a
future pipeline can atomically switch a fully indexed version into retrieval.
For now the indexer is an injected callable; the default records a stable
Qdrant reference and is intentionally deterministic in tests.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_VISIBILITIES = frozenset({"private", "public"})
_VERSION_STATUSES = frozenset({"draft", "indexing", "active", "archived", "failed", "expired"})
_MAX_TEXT_LENGTH = 50_000


class KnowledgeGovernanceError(RuntimeError):
    """Base error for document-governance operations."""


class KnowledgeNotFoundError(KnowledgeGovernanceError):
    """The caller cannot read the requested document/version."""


class KnowledgePermissionError(KnowledgeGovernanceError):
    """The caller can read a public document but cannot govern it."""


class KnowledgeValidationError(KnowledgeGovernanceError):
    """Document metadata or chunk data is invalid."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _as_text(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _safe(value: Any) -> Any:
    if isinstance(value, (datetime, date, uuid.UUID)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe(v) for v in value]
    return value


def _expired(value: str | datetime | date | None) -> bool:
    if not value:
        return False
    if isinstance(value, (datetime, date)):
        current = value
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            current = datetime.fromisoformat(text)
        except ValueError:
            return False
    if isinstance(current, date) and not isinstance(current, datetime):
        return current < datetime.now(UTC).date()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current < datetime.now(UTC)


def _validate_sha(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise KnowledgeValidationError("content_sha256 必须是 64 位 SHA-256")
    return normalized


def _validate_chunks(chunks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if chunks is None:
        return []
    if not isinstance(chunks, list) or len(chunks) > 10_000:
        raise KnowledgeValidationError("chunks 必须是有限数组")
    result: list[dict[str, Any]] = []
    for ordinal, raw in enumerate(chunks):
        if not isinstance(raw, dict):
            raise KnowledgeValidationError("每个 chunk 必须是 object")
        text = str(raw.get("text") or "").strip()
        if not text:
            raise KnowledgeValidationError("chunk 文本不能为空")
        if len(text) > _MAX_TEXT_LENGTH:
            raise KnowledgeValidationError("chunk 文本过长")
        page = raw.get("page")
        if page is not None:
            try:
                page = int(page)
            except (TypeError, ValueError) as exc:
                raise KnowledgeValidationError("chunk page 必须是整数") from exc
            if page < 1:
                raise KnowledgeValidationError("chunk page 必须为正整数")
        result.append({
            "ordinal": ordinal,
            "page": page,
            "text": text,
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
    return result


class KnowledgeGovernance:
    """Document/version/chunk lifecycle with FakeMemoryDb and PostgreSQL paths."""

    def __init__(self, db) -> None:
        self.db = db

    @property
    def _fake(self) -> bool:
        return self.db.__class__.__name__ == "FakeMemoryDb"

    def _state(self) -> dict[str, Any]:
        if not hasattr(self.db, "_knowledge_governance"):
            self.db._knowledge_governance = {
                "documents": {}, "versions": {}, "chunks": {},
                "citations": {}, "citation_requests": {},
            }
        state = self.db._knowledge_governance
        for key in ("documents", "versions", "chunks", "citations", "citation_requests"):
            state.setdefault(key, {})
        return state

    def _raw_document(
        self,
        owner_id: str,
        document_id: str,
        *,
        readable: bool = True,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        if self._fake:
            document = self._state()["documents"].get(document_id)
            if not document:
                raise KnowledgeNotFoundError("知识文档不存在或无权访问")
            if document["owner_id"] != owner_id and not is_admin and not (
                readable and document["visibility"] == "public"
            ):
                raise KnowledgeNotFoundError("知识文档不存在或无权访问")
            return document

        def _read(conn):
            if is_admin:
                row = conn.execute(
                    "SELECT id::text AS id,owner_id,name,category,visibility,status,active_version_id::text AS active_version_id,expires_at,credibility,created_at,updated_at "
                    "FROM knowledge_documents WHERE id=%s",
                    (document_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id::text AS id,owner_id,name,category,visibility,status,active_version_id::text AS active_version_id,expires_at,credibility,created_at,updated_at "
                    "FROM knowledge_documents WHERE id=%s AND (owner_id=%s OR visibility='public')",
                    (document_id, owner_id),
                ).fetchone()
            if not row:
                raise KnowledgeNotFoundError("知识文档不存在或无权访问")
            if not readable and row["owner_id"] != owner_id and not is_admin:
                raise KnowledgePermissionError("无权治理此知识文档")
            return dict(row)

        return self._pg(_read)

    def _governable_document(self, owner_id: str, document_id: str, *, is_admin: bool = False) -> dict[str, Any]:
        document = self._raw_document(owner_id, document_id, readable=True, is_admin=is_admin)
        if document.get("owner_id") != owner_id and not is_admin:
            raise KnowledgePermissionError("只有文档所有者或管理员可以治理知识文档")
        return document

    def create_document(
        self,
        owner_id: str,
        *,
        name: str,
        content_sha256: str,
        size_bytes: int,
        category: str = "knowledge",
        visibility: str = "private",
        mime_type: str = "application/octet-stream",
        expires_at: str | None = None,
        credibility: float = 1.0,
        chunks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        name = str(name or "").strip()
        if not name:
            raise KnowledgeValidationError("文档名称不能为空")
        if visibility not in _VISIBILITIES:
            raise KnowledgeValidationError("visibility 必须为 private 或 public")
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError) as exc:
            raise KnowledgeValidationError("size_bytes 必须是非负整数") from exc
        if size_bytes < 0:
            raise KnowledgeValidationError("size_bytes 必须是非负整数")
        if not 0 <= float(credibility) <= 1:
            raise KnowledgeValidationError("credibility 必须在 0 到 1 之间")
        content_sha256 = _validate_sha(content_sha256)
        prepared_chunks = _validate_chunks(chunks)
        if self._fake:
            duplicate = next(
                (doc for doc in self._state()["documents"].values()
                 if doc["owner_id"] == owner_id and any(
                     version["content_sha256"] == content_sha256
                     for version in self._state()["versions"].values()
                     if version["document_id"] == doc["id"]
                 )),
                None,
            )
            if duplicate:
                version = next(v for v in self._state()["versions"].values() if v["document_id"] == duplicate["id"] and v["content_sha256"] == content_sha256)
                return {"duplicate": True, "document_id": duplicate["id"], "version_id": version["id"]}
            document_id = str(uuid.uuid4())
            now = _now()
            document = {
                "id": document_id, "owner_id": owner_id, "name": name,
                "category": category or "knowledge", "visibility": visibility,
                "status": "active", "active_version_id": None,
                "expires_at": expires_at, "credibility": float(credibility),
                "created_at": now, "updated_at": now,
            }
            self._state()["documents"][document_id] = document
            version = self._create_fake_version(
                document, content_sha256=content_sha256, size_bytes=size_bytes,
                mime_type=mime_type, expires_at=expires_at, credibility=float(credibility),
                chunks=prepared_chunks,
            )
            return {"duplicate": False, "document_id": document_id, "version_id": version["id"]}

        def _create(conn):
            existing = conn.execute(
                "SELECT d.id::text AS document_id,v.id::text AS version_id FROM knowledge_documents d "
                "JOIN knowledge_document_versions v ON v.document_id=d.id "
                "WHERE d.owner_id=%s AND v.content_sha256=%s LIMIT 1",
                (owner_id, content_sha256),
            ).fetchone()
            if existing:
                return {"duplicate": True, "document_id": str(existing["document_id"]), "version_id": str(existing["version_id"])}
            document_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO knowledge_documents (id,owner_id,name,category,visibility,status,expires_at,credibility) VALUES (%s,%s,%s,%s,%s,'active',%s,%s)",
                (document_id, owner_id, name, category or "knowledge", visibility, expires_at, float(credibility)),
            )
            version = self._insert_pg_version(
                conn, document_id, content_sha256=content_sha256, size_bytes=size_bytes,
                mime_type=mime_type, expires_at=expires_at, credibility=float(credibility), chunks=prepared_chunks,
            )
            return {"duplicate": False, "document_id": document_id, "version_id": version["id"]}

        return self._pg(_create)

    def _create_fake_version(self, document: dict[str, Any], *, content_sha256: str, size_bytes: int, mime_type: str, expires_at: str | None, credibility: float, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        state = self._state()
        version_id = str(uuid.uuid4())
        existing_numbers = [
            int(v["version_number"]) for v in state["versions"].values()
            if v["document_id"] == document["id"]
        ]
        version = {
            "id": version_id, "document_id": document["id"],
            "version_number": max(existing_numbers, default=0) + 1,
            "content_sha256": content_sha256, "size_bytes": size_bytes,
            "mime_type": mime_type or "application/octet-stream", "status": "draft",
            "expires_at": expires_at, "credibility": credibility,
            "indexed_at": None, "created_at": _now(), "updated_at": _now(),
        }
        state["versions"][version_id] = version
        for chunk in chunks:
            chunk_id = str(uuid.uuid4())
            state["chunks"][chunk_id] = {
                "id": chunk_id, "version_id": version_id, **chunk,
                "index_status": "pending", "qdrant_point_id": None,
                "created_at": _now(), "updated_at": _now(),
            }
        return version

    def create_version(
        self,
        owner_id: str,
        document_id: str,
        *,
        content_sha256: str,
        size_bytes: int,
        mime_type: str = "application/octet-stream",
        expires_at: str | None = None,
        credibility: float | None = None,
        chunks: list[dict[str, Any]] | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        document = self._governable_document(owner_id, document_id, is_admin=is_admin)
        content_sha256 = _validate_sha(content_sha256)
        prepared_chunks = _validate_chunks(chunks)
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError) as exc:
            raise KnowledgeValidationError("size_bytes 必须是非负整数") from exc
        if size_bytes < 0:
            raise KnowledgeValidationError("size_bytes 必须是非负整数")
        if credibility is None:
            credibility = float(document.get("credibility") or 1.0)
        if not 0 <= float(credibility) <= 1:
            raise KnowledgeValidationError("credibility 必须在 0 到 1 之间")
        if self._fake:
            for version in self._state()["versions"].values():
                if version["document_id"] == document_id and version["content_sha256"] == content_sha256:
                    raise KnowledgeValidationError("同一文档已存在相同内容版本")
            return {
                "duplicate": False,
                "document_id": document_id,
                "version_id": self._create_fake_version(
                    document, content_sha256=content_sha256, size_bytes=int(size_bytes),
                    mime_type=mime_type, expires_at=expires_at or document.get("expires_at"),
                    credibility=float(credibility), chunks=prepared_chunks,
                )["id"],
            }

        def _create(conn):
            version = self._insert_pg_version(
                conn, document_id, content_sha256=content_sha256, size_bytes=int(size_bytes),
                mime_type=mime_type, expires_at=expires_at or document.get("expires_at"),
                credibility=float(credibility), chunks=prepared_chunks,
            )
            return {"duplicate": False, "document_id": document_id, "version_id": version["id"]}

        return self._pg(_create)

    def update_document(
        self,
        owner_id: str,
        document_id: str,
        *,
        expires_at: str | None | object = None,
        credibility: float | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        document = self._governable_document(owner_id, document_id, is_admin=is_admin)
        if credibility is not None and not 0 <= float(credibility) <= 1:
            raise KnowledgeValidationError("credibility 必须在 0 到 1 之间")
        if self._fake:
            if expires_at is not None:
                document["expires_at"] = expires_at
            if credibility is not None:
                document["credibility"] = float(credibility)
            document["updated_at"] = _now()
            for version in self._state()["versions"].values():
                if version["document_id"] == document_id and expires_at is not None:
                    version["expires_at"] = expires_at
                if version["document_id"] == document_id and credibility is not None:
                    version["credibility"] = float(credibility)
            return self._detail_from_fake(document)

        def _update(conn):
            fields: list[str] = []
            params: list[Any] = []
            if expires_at is not None:
                fields.append("expires_at=%s")
                params.append(expires_at)
            if credibility is not None:
                fields.append("credibility=%s")
                params.append(float(credibility))
            if fields:
                params.extend([document_id])
                conn.execute(f"UPDATE knowledge_documents SET {', '.join(fields)},updated_at=now() WHERE id=%s", tuple(params))
                if expires_at is not None:
                    conn.execute("UPDATE knowledge_document_versions SET expires_at=%s,updated_at=now() WHERE document_id=%s", (expires_at, document_id))
                if credibility is not None:
                    conn.execute("UPDATE knowledge_document_versions SET credibility=%s,updated_at=now() WHERE document_id=%s", (float(credibility), document_id))
            return self._get_detail_pg(conn, owner_id, document_id, is_admin=is_admin)

        return self._pg(_update)

    def list_documents(self, owner_id: str, *, include_expired: bool = False) -> list[dict[str, Any]]:
        if self._fake:
            rows = []
            for document in self._state()["documents"].values():
                if document["owner_id"] != owner_id and document["visibility"] != "public":
                    continue
                if document["status"] == "deleted":
                    continue
                if not include_expired and _expired(document.get("expires_at")):
                    continue
                detail = self._detail_from_fake(document)
                if not include_expired and detail["active_version_id"] is None:
                    continue
                rows.append(detail)
            rows.sort(key=lambda row: (str(row.get("updated_at") or ""), str(row["id"])), reverse=True)
            return rows

        def _list(conn):
            rows = conn.execute(
                "SELECT id::text AS id,owner_id,name,category,visibility,status,active_version_id::text AS active_version_id,expires_at,credibility,created_at,updated_at "
                "FROM knowledge_documents WHERE (owner_id=%s OR visibility='public') AND status<>'deleted' "
                + ("" if include_expired else "AND (expires_at IS NULL OR expires_at>now())")
                + " ORDER BY updated_at DESC,id DESC",
                (owner_id,),
            ).fetchall()
            return [self._get_detail_pg(conn, owner_id, str(row["id"])) for row in rows]

        return self._pg(_list)

    def get_document(self, owner_id: str, document_id: str, *, is_admin: bool = False) -> dict[str, Any]:
        document = self._raw_document(owner_id, document_id, is_admin=is_admin)
        if self._fake:
            return self._detail_from_fake(document)

        def _read(conn):
            return self._get_detail_pg(conn, owner_id, document_id, is_admin=is_admin)

        return self._pg(_read)

    def reindex(
        self,
        owner_id: str,
        document_id: str,
        version_id: str,
        *,
        indexer: Callable[[dict[str, Any]], str | None] | None = None,
        allow_expired: bool = False,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        document = self._governable_document(owner_id, document_id, is_admin=is_admin)
        if self._fake:
            state = self._state()
            version = state["versions"].get(version_id)
            if not version or version["document_id"] != document_id:
                raise KnowledgeNotFoundError("知识版本不存在或无权访问")
            if _expired(version.get("expires_at")) and not allow_expired:
                raise KnowledgeValidationError("知识版本已过期，请先续期")
            chunks = sorted((c for c in state["chunks"].values() if c["version_id"] == version_id), key=lambda c: c["ordinal"])
            version["status"] = "indexing"
            try:
                for chunk in chunks:
                    point = indexer(chunk) if indexer else f"knowledge:{version_id}:{chunk['ordinal']}"
                    chunk["qdrant_point_id"] = point or f"knowledge:{version_id}:{chunk['ordinal']}"
                    chunk["index_status"] = "indexed"
                    chunk["updated_at"] = _now()
            except Exception:
                version["status"] = "failed"
                for chunk in chunks:
                    if chunk["index_status"] != "indexed":
                        chunk["index_status"] = "failed"
                version["updated_at"] = _now()
                raise
            for old in state["versions"].values():
                if old["document_id"] == document_id and old["id"] != version_id and old["status"] == "active":
                    old["status"] = "archived"
                    old["updated_at"] = _now()
            version["status"] = "active"
            version["indexed_at"] = _now()
            version["updated_at"] = _now()
            document["active_version_id"] = version_id
            document["updated_at"] = _now()
            return self._detail_from_fake(document)

        def _reindex(conn):
            version = conn.execute(
                "SELECT id::text AS id,document_id::text AS document_id,status,expires_at FROM knowledge_document_versions WHERE id=%s AND document_id=%s",
                (version_id, document_id),
            ).fetchone()
            if not version:
                raise KnowledgeNotFoundError("知识版本不存在或无权访问")
            if _expired(version["expires_at"]) and not allow_expired:
                raise KnowledgeValidationError("知识版本已过期，请先续期")
            chunks = [dict(row) for row in conn.execute(
                "SELECT id::text AS id,ordinal,page,text,text_hash,index_status,qdrant_point_id FROM knowledge_document_chunks WHERE version_id=%s ORDER BY ordinal",
                (version_id,),
            ).fetchall()]
            conn.execute("UPDATE knowledge_document_versions SET status='indexing',updated_at=now() WHERE id=%s", (version_id,))
            try:
                for chunk in chunks:
                    point = indexer(chunk) if indexer else f"knowledge:{version_id}:{chunk['ordinal']}"
                    conn.execute("UPDATE knowledge_document_chunks SET qdrant_point_id=%s,index_status='indexed',updated_at=now() WHERE id=%s", (point or f"knowledge:{version_id}:{chunk['ordinal']}", chunk["id"]))
            except Exception:
                conn.execute("UPDATE knowledge_document_versions SET status='failed',updated_at=now() WHERE id=%s", (version_id,))
                conn.execute("UPDATE knowledge_document_chunks SET index_status='failed',updated_at=now() WHERE version_id=%s AND index_status<>'indexed'", (version_id,))
                raise
            conn.execute("UPDATE knowledge_document_versions SET status='archived',updated_at=now() WHERE document_id=%s AND status='active' AND id<>%s", (document_id, version_id))
            conn.execute("UPDATE knowledge_document_versions SET status='active',indexed_at=now(),updated_at=now() WHERE id=%s", (version_id,))
            conn.execute("UPDATE knowledge_documents SET active_version_id=%s,updated_at=now() WHERE id=%s", (version_id, document_id))
            return self._get_detail_pg(conn, owner_id, document_id, is_admin=is_admin)

        return self._pg(_reindex)

    def record_citations(
        self,
        owner_id: str,
        document_id: str,
        version_id: str,
        chunk_ids: list[str],
        *,
        request_id: str,
    ) -> dict[str, int]:
        self._raw_document(owner_id, document_id)
        request_id = str(request_id or "").strip()
        if not request_id or len(request_id) > 128:
            raise KnowledgeValidationError("request_id 无效")
        unique_ids = list(dict.fromkeys(str(value) for value in chunk_ids))
        if self._fake:
            state = self._state()
            version = state["versions"].get(version_id)
            if not version or version["document_id"] != document_id:
                raise KnowledgeNotFoundError("知识版本不存在或无权访问")
            valid_chunks = {
                chunk["id"] for chunk in state["chunks"].values() if chunk["version_id"] == version_id
            }
            if any(chunk_id not in valid_chunks for chunk_id in unique_ids):
                raise KnowledgeNotFoundError("知识分块不存在或无权访问")
            request_key = f"{owner_id}:{request_id}"
            seen = state["citation_requests"].setdefault(request_key, set())
            counts: dict[str, int] = {}
            for chunk_id in unique_ids:
                key = (document_id, version_id, chunk_id)
                entry = state["citations"].setdefault(key, {"count": 0, "first_at": _now(), "last_at": _now()})
                if chunk_id not in seen:
                    entry["count"] += 1
                    entry["last_at"] = _now()
                    seen.add(chunk_id)
                counts[chunk_id] = int(entry["count"])
            return counts

        def _cite(conn):
            version = conn.execute(
                "SELECT 1 FROM knowledge_document_versions WHERE id=%s AND document_id=%s",
                (version_id, document_id),
            ).fetchone()
            if not version:
                raise KnowledgeNotFoundError("知识版本不存在或无权访问")
            valid = {
                str(row["id"]) for row in conn.execute(
                    "SELECT id::text AS id FROM knowledge_document_chunks WHERE version_id=%s AND id=ANY(%s::uuid[])",
                    (version_id, unique_ids),
                ).fetchall()
            }
            if len(valid) != len(unique_ids):
                raise KnowledgeNotFoundError("知识分块不存在或无权访问")
            counts: dict[str, int] = {}
            for chunk_id in unique_ids:
                row = conn.execute(
                    "INSERT INTO knowledge_citation_events (id,owner_id,document_id,version_id,chunk_id,request_id,count) VALUES (%s,%s,%s,%s,%s,%s,1) "
                    "ON CONFLICT (owner_id,request_id,chunk_id) DO UPDATE SET last_at=now() RETURNING count",
                    (str(uuid.uuid4()), owner_id, document_id, version_id, chunk_id, request_id),
                ).fetchone()
                counts[chunk_id] = int(row["count"])
            return counts

        return self._pg(_cite)

    # ── fake detail helpers ───────────────────────────────────────────────

    def _detail_from_fake(self, document: dict[str, Any]) -> dict[str, Any]:
        state = self._state()
        versions: list[dict[str, Any]] = []
        for version in state["versions"].values():
            if version["document_id"] != document["id"]:
                continue
            chunks = [
                _safe(dict(chunk)) for chunk in state["chunks"].values()
                if chunk["version_id"] == version["id"]
            ]
            chunks.sort(key=lambda chunk: chunk["ordinal"])
            hits = sum(
                int(entry["count"]) for key, entry in state["citations"].items()
                if key[0] == document["id"] and key[1] == version["id"]
            )
            versions.append({**_safe(version), "chunks": chunks, "citation_hits": hits})
        versions.sort(key=lambda version: version["version_number"], reverse=True)
        result = {**_safe(document), "versions": versions}
        result["citation_hits"] = sum(int(version["citation_hits"]) for version in versions)
        if _expired(result.get("expires_at")):
            result["status"] = "expired"
        return result

    # ── PostgreSQL helpers ────────────────────────────────────────────────

    def _pg(self, callback):
        borrow = getattr(self.db, "_borrow", None)
        if borrow is None:
            raise KnowledgeValidationError("知识治理数据库不可用")
        with self.db.write_lock, borrow() as conn:
            return callback(conn)

    @staticmethod
    def _insert_pg_version(conn, document_id: str, *, content_sha256: str, size_bytes: int, mime_type: str, expires_at: str | None, credibility: float, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        version_id = str(uuid.uuid4())
        row = conn.execute(
            "INSERT INTO knowledge_document_versions (id,document_id,version_number,content_sha256,size_bytes,mime_type,status,expires_at,credibility) "
            "SELECT %s,%s,COALESCE(MAX(version_number),0)+1,%s,%s,%s,'draft',%s,%s FROM knowledge_document_versions WHERE document_id=%s RETURNING id::text AS id,version_number",
            (version_id, document_id, content_sha256, size_bytes, mime_type or "application/octet-stream", expires_at, credibility, document_id),
        ).fetchone()
        for chunk in chunks:
            conn.execute(
                "INSERT INTO knowledge_document_chunks (id,version_id,ordinal,page,text,text_hash,index_status) VALUES (%s,%s,%s,%s,%s,%s,'pending')",
                (str(uuid.uuid4()), version_id, chunk["ordinal"], chunk["page"], chunk["text"], chunk["text_hash"]),
            )
        return {"id": version_id, "version_number": row["version_number"]}

    @staticmethod
    def _get_detail_pg(
        conn, owner_id: str, document_id: str, *, is_admin: bool = False
    ) -> dict[str, Any]:
        if is_admin:
            row = conn.execute(
                "SELECT id::text AS id,owner_id,name,category,visibility,status,active_version_id::text AS active_version_id,expires_at,credibility,created_at,updated_at FROM knowledge_documents WHERE id=%s",
                (document_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id::text AS id,owner_id,name,category,visibility,status,active_version_id::text AS active_version_id,expires_at,credibility,created_at,updated_at FROM knowledge_documents WHERE id=%s AND (owner_id=%s OR visibility='public')",
                (document_id, owner_id),
            ).fetchone()
        if not row:
            raise KnowledgeNotFoundError("知识文档不存在或无权访问")
        document = dict(row)
        versions = [dict(item) for item in conn.execute(
            "SELECT id::text AS id,document_id::text AS document_id,version_number,content_sha256,size_bytes,mime_type,status,expires_at,credibility,indexed_at,created_at,updated_at FROM knowledge_document_versions WHERE document_id=%s ORDER BY version_number DESC",
            (document_id,),
        ).fetchall()]
        for version in versions:
            chunks = [dict(item) for item in conn.execute(
                "SELECT id::text AS id,version_id::text AS version_id,ordinal,page,text,text_hash,index_status,qdrant_point_id,created_at,updated_at FROM knowledge_document_chunks WHERE version_id=%s ORDER BY ordinal",
                (version["id"],),
            ).fetchall()]
            version["chunks"] = [_safe(chunk) for chunk in chunks]
            hit = conn.execute(
                "SELECT COALESCE(SUM(count),0) AS hits FROM knowledge_citation_events WHERE document_id=%s AND version_id=%s",
                (document_id, version["id"]),
            ).fetchone()
            version["citation_hits"] = int(hit["hits"] or 0)
        document["versions"] = [_safe(version) for version in versions]
        document["citation_hits"] = sum(int(version["citation_hits"]) for version in versions)
        if _expired(document.get("expires_at")):
            document["status"] = "expired"
        return _safe(document)


__all__ = [
    "KnowledgeGovernance", "KnowledgeGovernanceError", "KnowledgeNotFoundError",
    "KnowledgePermissionError", "KnowledgeValidationError",
]
