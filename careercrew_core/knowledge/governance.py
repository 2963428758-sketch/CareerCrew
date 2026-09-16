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
from datetime import UTC, date, datetime, timedelta
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_VISIBILITIES = frozenset({"private", "public"})
_VERSION_STATUSES = frozenset({"draft", "indexing", "active", "archived", "failed", "expired"})
_MAX_TEXT_LENGTH = 50_000
_STALE_INDEXING_SECONDS = 1800


class KnowledgeGovernanceError(RuntimeError):
    """Base error for document-governance operations."""


class KnowledgeNotFoundError(KnowledgeGovernanceError):
    """The caller cannot read the requested document/version."""


class KnowledgePermissionError(KnowledgeGovernanceError):
    """The caller can read a public document but cannot govern it."""


class KnowledgeConflictError(KnowledgeGovernanceError):
    """The caller edited a stale representation of a governed resource."""


class KnowledgeIndexingError(KnowledgeGovernanceError):
    """The external vector projection could not be updated."""


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


def _next_now(previous: Any = None) -> str:
    """Return a strictly newer fake timestamp when the clock is coarse/frozen."""

    current = datetime.now(UTC)
    if previous:
        try:
            previous_dt = datetime.fromisoformat(str(previous).replace("Z", "+00:00"))
            if previous_dt.tzinfo is None:
                previous_dt = previous_dt.replace(tzinfo=UTC)
            if current <= previous_dt:
                current = previous_dt + timedelta(microseconds=1)
        except ValueError:
            pass
    return current.isoformat()


def _safe(value: Any) -> Any:
    if isinstance(value, (datetime, date, uuid.UUID)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe(v) for v in value]
    return value


def _normalize_expiry(value: Any) -> str | None:
    """Normalize an API expiry to an unambiguous UTC ISO datetime."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise KnowledgeValidationError("expires_at 必须是 ISO 日期或日期时间")
    if isinstance(value, datetime):
        current = value
    elif isinstance(value, date):
        current = datetime.combine(value, datetime.max.time())
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise KnowledgeValidationError("expires_at 必须是 ISO 日期或日期时间")
        try:
            if len(text) == 10 and text[4] == "-" and text[7] == "-":
                current = datetime.combine(date.fromisoformat(text), datetime.max.time())
            else:
                current = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise KnowledgeValidationError("expires_at 必须是 ISO 日期或日期时间") from exc
    else:
        raise KnowledgeValidationError("expires_at 必须是 ISO 日期或日期时间")
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


def _expired(value: str | datetime | date | None) -> bool:
    normalized = _normalize_expiry(value)
    if normalized is None:
        return False
    current = datetime.fromisoformat(normalized)
    return current < datetime.now(UTC)


def _validate_sha(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise KnowledgeValidationError("content_sha256 必须是 64 位 SHA-256")
    return normalized


def _validate_uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise KnowledgeValidationError(f"{field} 必须是 UUID") from exc


def _same_timestamp(expected: str, actual: Any) -> bool:
    """Compare API ISO timestamps with psycopg datetime values safely."""

    expected_text = str(expected).strip().replace("Z", "+00:00")
    actual_text = str(_as_text(actual)).strip().replace("Z", "+00:00")
    try:
        expected_dt = datetime.fromisoformat(expected_text)
        actual_dt = datetime.fromisoformat(actual_text)
    except ValueError:
        return expected_text == actual_text
    if expected_dt.tzinfo is None:
        expected_dt = expected_dt.replace(tzinfo=UTC)
    if actual_dt.tzinfo is None:
        actual_dt = actual_dt.replace(tzinfo=UTC)
    return expected_dt == actual_dt


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


def _chunk_content_metadata(chunks: list[dict[str, Any]]) -> tuple[str, int]:
    """Build a stable digest/size for a governed version's current chunks."""

    canonical = "\n".join(
        f"{int(chunk['ordinal'])}\t{'' if chunk.get('page') is None else int(chunk['page'])}\t{chunk['text']}"
        for chunk in sorted(chunks, key=lambda item: int(item["ordinal"]))
    )
    encoded = canonical.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


class KnowledgeGovernance:
    """Document/version/chunk lifecycle with FakeMemoryDb and PostgreSQL paths."""

    def __init__(self, db, *, vector_store=None) -> None:
        self.db = db
        # Optional external projection.  Keeping this dependency injected
        # makes the relational service testable while allowing the API route to
        # retire/activate Qdrant points at the same lifecycle boundary.
        self.vector_store = vector_store

    def _governance_vector_filters(
        self, document_id: str, *, version_id: str | None = None,
        chunk_id: str | None = None,
    ) -> dict[str, str]:
        filters = {
            "record_type": "knowledge_governance",
            "governance_document_id": document_id,
        }
        if version_id:
            filters["governance_version_id"] = version_id
        if chunk_id:
            filters["governance_chunk_id"] = chunk_id
        return filters

    def _set_governance_vector_status(
        self, document_id: str, version_id: str, status: str,
    ) -> int:
        setter = getattr(self.vector_store, "set_payload_by_filter", None)
        if not callable(setter):
            return 0
        try:
            return int(setter(
                {"governance_status": status},
                self._governance_vector_filters(document_id, version_id=version_id),
            ) or 0)
        except Exception as exc:
            raise KnowledgeIndexingError("知识向量状态切换失败") from exc

    def _delete_governance_vectors(self, filters: dict[str, str]) -> int:
        deleter = getattr(self.vector_store, "delete_by_metadata", None)
        if not callable(deleter):
            return 0
        try:
            return int(deleter(filters) or 0)
        except Exception as exc:
            raise KnowledgeIndexingError("知识向量清理失败") from exc

    def _invalidate_chunk_vector(
        self, document_id: str, version_id: str, chunk_id: str,
    ) -> int:
        """Remove the whole projection because editing invalidates the version."""

        return self._delete_governance_vectors(
            self._governance_vector_filters(
                document_id, version_id=version_id,
            )
        )

    def _retire_version_vectors(self, document_id: str, version_ids: set[str]) -> None:
        for old_version_id in version_ids:
            self._set_governance_vector_status(document_id, old_version_id, "retiring")

    def _activate_vector_projection(
        self,
        document_id: str,
        version_id: str,
        old_version_ids: set[str],
        expected_chunks: int,
        visibility: str = "private",
        cleanup: bool = True,
    ) -> None:
        """Activate a prepared projection while the caller holds the writer lock.

        Old projections are marked ``retiring`` before the relational cutover,
        so a cleanup failure cannot make stale content visible.  Physical
        deletion can be deferred until after PostgreSQL commits; a later retry
        can safely repeat the exact metadata delete.
        """

        # The indexer may have captured metadata before the document lock was
        # acquired. Correct its payload while still staged, before activation.
        if self.vector_store is not None:
            self.vector_store.set_payload_by_filter(
                {"visibility": visibility},
                self._governance_vector_filters(document_id, version_id=version_id),
            )
        updated = self._set_governance_vector_status(document_id, version_id, "active")
        if self.vector_store is not None and updated < expected_chunks:
            raise KnowledgeIndexingError("知识版本向量激活校验未覆盖全部分块")
        for old_version_id in (old_version_ids - {version_id}) if cleanup else ():
            self._delete_governance_vectors(
                self._governance_vector_filters(document_id, version_id=old_version_id)
            )

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
        expires_at: str | datetime | date | None = None,
        credibility: float = 1.0,
        chunks: list[dict[str, Any]] | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        name = str(name or "").strip()
        if not name:
            raise KnowledgeValidationError("文档名称不能为空")
        if visibility not in _VISIBILITIES:
            raise KnowledgeValidationError("visibility 必须为 private 或 public")
        if visibility == "public" and not is_admin:
            raise KnowledgePermissionError("只有管理员可以创建公共知识文档")
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError) as exc:
            raise KnowledgeValidationError("size_bytes 必须是非负整数") from exc
        if size_bytes < 0:
            raise KnowledgeValidationError("size_bytes 必须是非负整数")
        if not 0 <= float(credibility) <= 1:
            raise KnowledgeValidationError("credibility 必须在 0 到 1 之间")
        content_sha256 = _validate_sha(content_sha256)
        expires_at = _normalize_expiry(expires_at)
        prepared_chunks = _validate_chunks(chunks)
        if self._fake:
            duplicate = next(
                (doc for doc in self._state()["documents"].values()
                 if doc["owner_id"] == owner_id and any(
                     version.get("source_content_sha256", version["content_sha256"]) == content_sha256
                     for version in self._state()["versions"].values()
                     if version["document_id"] == doc["id"]
                 )),
                None,
            )
            if duplicate:
                version = next(
                    v for v in self._state()["versions"].values()
                    if v["document_id"] == duplicate["id"]
                    and v.get("source_content_sha256", v["content_sha256"]) == content_sha256
                )
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
                "WHERE d.owner_id=%s AND COALESCE(v.source_content_sha256,v.content_sha256)=%s LIMIT 1",
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
            "source_content_sha256": content_sha256, "source_size_bytes": size_bytes,
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
        expires_at: str | datetime | date | None = None,
        credibility: float | None = None,
        chunks: list[dict[str, Any]] | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        document_id = _validate_uuid(document_id, "document_id")
        document = self._governable_document(owner_id, document_id, is_admin=is_admin)
        content_sha256 = _validate_sha(content_sha256)
        expires_at = _normalize_expiry(expires_at)
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
                if (
                    version["document_id"] == document_id
                    and version.get("source_content_sha256", version["content_sha256"]) == content_sha256
                ):
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

    def unpublish_document(self, owner_id: str, document_id: str) -> int:
        return self._change_visibility(owner_id, document_id, "private")

    def publish_document(self, owner_id: str, document_id: str) -> int:
        return self._change_visibility(owner_id, document_id, "public")

    def _change_visibility(self, owner_id: str, document_id: str, visibility: str) -> int:
        """Change both stores while serialized against indexing and editing.

        Never change projection status here: archived versions must stay inactive.
        A vector failure leaves the operation failed and retryable.
        """
        document_id = _validate_uuid(document_id, "document_id")
        document = self._governable_document(owner_id, document_id)

        def project(value: str) -> int:
            if self.vector_store is None:
                raise KnowledgeIndexingError("知识向量服务暂不可用")
            try:
                return self.vector_store.set_payload_by_filter(
                    {"visibility": value},
                    {"owner_user_id": owner_id, "doc": "governance:" + document_id},
                )
            except Exception as exc:
                raise KnowledgeIndexingError("知识可见性更新失败") from exc

        if self._fake:
            with self.db.write_lock:
                try:
                    count = project(visibility)
                except Exception:
                    project(document["visibility"])
                    raise
                document.update(visibility=visibility, updated_at=_now())
                return count

        def update(conn):
            row = conn.execute(
                "SELECT id FROM knowledge_documents WHERE id=%s AND owner_id=%s FOR UPDATE",
                (document_id, owner_id),
            ).fetchone()
            if row is None:
                raise KnowledgeNotFoundError("知识文档不存在或无权访问")
            conn.execute(
                "UPDATE knowledge_documents SET visibility=%s,updated_at=now() WHERE id=%s",
                (visibility, document_id),
            )
            return project(visibility)

        def reconcile(conn):
            # The previous commit may have failed or its response may have been
            # lost. Re-read under the same row lock as writers; never compensate
            # from the stale pre-request snapshot over a newer worker's change.
            row = conn.execute(
                "SELECT visibility FROM knowledge_documents WHERE id=%s AND owner_id=%s FOR UPDATE",
                (document_id, owner_id),
            ).fetchone()
            project(row["visibility"] if row else "private")

        try:
            return self._pg(update)
        except Exception:
            self._pg(reconcile)
            raise

    def update_document(
        self,
        owner_id: str,
        document_id: str,
        *,
        expires_at: str | datetime | date | None | object = None,
        credibility: float | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        document_id = _validate_uuid(document_id, "document_id")
        document = self._governable_document(owner_id, document_id, is_admin=is_admin)
        if expires_at is not None:
            expires_at = _normalize_expiry(expires_at)
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

    def update_chunk(
        self,
        owner_id: str,
        document_id: str,
        version_id: str,
        chunk_id: str,
        *,
        text: str,
        page: int | None = None,
        expected_updated_at: str | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        """Edit one governed chunk and invalidate its containing index.

        Editing an active version removes its active pointer until an explicit
        reindex succeeds.  This prevents an old Qdrant projection from being
        presented as the edited content.  The draft version digest is rebuilt
        from its current ordered chunks so metadata cannot describe stale text.
        """
        document_id = _validate_uuid(document_id, "document_id")
        version_id = _validate_uuid(version_id, "version_id")
        chunk_id = _validate_uuid(chunk_id, "chunk_id")
        if expected_updated_at is not None and not str(expected_updated_at).strip():
            raise KnowledgeValidationError("expected_updated_at 无效")
        document = self._governable_document(owner_id, document_id, is_admin=is_admin)
        prepared = _validate_chunks([{"text": text, "page": page}])[0]

        if self._fake:
            state = self._state()
            version = state["versions"].get(version_id)
            if not version or version["document_id"] != document_id:
                raise KnowledgeNotFoundError("知识版本不存在或无权访问")
            chunk = state["chunks"].get(chunk_id)
            if not chunk or chunk["version_id"] != version_id:
                raise KnowledgeNotFoundError("知识分块不存在或无权访问")
            if expected_updated_at is not None and not _same_timestamp(
                expected_updated_at, chunk.get("updated_at"),
            ):
                raise KnowledgeConflictError("知识分块已被其他请求修改，请刷新后重试")
            chunks = [
                dict(item) for item in state["chunks"].values()
                if item["version_id"] == version_id
            ]
            updated_chunk = {**chunk, "text": prepared["text"], "page": prepared["page"]}
            content_sha256, size_bytes = _chunk_content_metadata(
                [updated_chunk if item["id"] == chunk_id else item for item in chunks]
            )
            duplicate = next(
                (
                    item for item in state["versions"].values()
                    if item["document_id"] == document_id
                    and item["id"] != version_id
                    and item.get("content_sha256") == content_sha256
                ),
                None,
            )
            if duplicate:
                raise KnowledgeValidationError("编辑后内容与已有版本重复")
            # Rejected/conflicting edits must not mutate the vector projection.
            self._invalidate_chunk_vector(document_id, version_id, chunk_id)
            was_active = (
                str(document.get("active_version_id") or "") == version_id
                or version.get("status") == "active"
            )
            chunk.update(
                text=prepared["text"], page=prepared["page"],
                text_hash=prepared["text_hash"], index_status="pending",
                qdrant_point_id=None,
                updated_at=_next_now(chunk.get("updated_at")),
            )
            for sibling in state["chunks"].values():
                if sibling["version_id"] == version_id:
                    sibling.update(index_status="pending", qdrant_point_id=None)
            version.update(
                content_sha256=content_sha256, size_bytes=size_bytes,
                status="draft", indexed_at=None, updated_at=_now(),
            )
            if was_active:
                document["active_version_id"] = None
            document["updated_at"] = _now()
            return self._detail_from_fake(document)

        def _update(conn):
            locked_document = conn.execute(
                "SELECT id::text AS id,owner_id,visibility,status,active_version_id::text AS active_version_id "
                "FROM knowledge_documents WHERE id=%s FOR UPDATE",
                (document_id,),
            ).fetchone()
            if not locked_document:
                raise KnowledgeNotFoundError("知识文档不存在或无权访问")
            version = conn.execute(
                "SELECT id::text AS id,status,content_sha256,size_bytes FROM knowledge_document_versions "
                "WHERE id=%s AND document_id=%s FOR UPDATE",
                (version_id, document_id),
            ).fetchone()
            if not version:
                raise KnowledgeNotFoundError("知识版本不存在或无权访问")
            chunk = conn.execute(
                "SELECT id::text AS id,ordinal,page,text,text_hash,index_status,qdrant_point_id,updated_at FROM knowledge_document_chunks "
                "WHERE id=%s AND version_id=%s FOR UPDATE",
                (chunk_id, version_id),
            ).fetchone()
            if not chunk:
                raise KnowledgeNotFoundError("知识分块不存在或无权访问")
            if expected_updated_at is not None and not _same_timestamp(
                expected_updated_at, chunk["updated_at"],
            ):
                raise KnowledgeConflictError("知识分块已被其他请求修改，请刷新后重试")
            chunks = [dict(row) for row in conn.execute(
                "SELECT id::text AS id,ordinal,page,text FROM knowledge_document_chunks "
                "WHERE version_id=%s ORDER BY ordinal",
                (version_id,),
            ).fetchall()]
            updated_chunks = [
                {**item, "text": prepared["text"], "page": prepared["page"]}
                if str(item["id"]) == chunk_id else item
                for item in chunks
            ]
            content_sha256, size_bytes = _chunk_content_metadata(updated_chunks)
            duplicate = conn.execute(
                "SELECT 1 FROM knowledge_document_versions "
                "WHERE document_id=%s AND content_sha256=%s AND id<>%s LIMIT 1",
                (document_id, content_sha256, version_id),
            ).fetchone()
            if duplicate:
                raise KnowledgeValidationError("编辑后内容与已有版本重复")
            # Validate under the row locks before touching the external index.
            self._invalidate_chunk_vector(document_id, version_id, chunk_id)
            chunk_update = conn.execute(
                "UPDATE knowledge_document_chunks SET text=%s,text_hash=%s,page=%s,"
                "index_status='pending',qdrant_point_id=NULL,updated_at=now() WHERE id=%s AND version_id=%s",
                (prepared["text"], prepared["text_hash"], prepared["page"], chunk_id, version_id),
            )
            if getattr(chunk_update, "rowcount", 1) != 1:
                raise KnowledgeNotFoundError("知识分块不存在或无权访问")
            conn.execute(
                "UPDATE knowledge_document_chunks SET index_status='pending',qdrant_point_id=NULL WHERE version_id=%s",
                (version_id,),
            )
            version_update = conn.execute(
                "UPDATE knowledge_document_versions SET content_sha256=%s,size_bytes=%s,status='draft',"
                "indexed_at=NULL,updated_at=now() WHERE id=%s AND document_id=%s",
                (content_sha256, size_bytes, version_id, document_id),
            )
            if getattr(version_update, "rowcount", 1) != 1:
                raise KnowledgeNotFoundError("知识版本不存在或无权访问")
            if (
                str(locked_document.get("active_version_id") or "") == version_id
                or version["status"] == "active"
            ):
                conn.execute(
                    "UPDATE knowledge_documents SET active_version_id=NULL,updated_at=now() WHERE id=%s",
                    (document_id,),
                )
            else:
                conn.execute(
                    "UPDATE knowledge_documents SET updated_at=now() WHERE id=%s",
                    (document_id,),
                )
            return self._get_detail_pg(conn, owner_id, document_id, is_admin=is_admin)

        return self._pg(_update)

    def list_documents(
        self,
        owner_id: str,
        *,
        include_expired: bool = False,
        is_admin: bool = False,
    ) -> list[dict[str, Any]]:
        self.recover_stale_indexing(
            None if is_admin else owner_id,
            stale_after_seconds=_STALE_INDEXING_SECONDS,
        )
        if self._fake:
            rows = []
            for document in self._state()["documents"].values():
                if (
                    not is_admin
                    and document["owner_id"] != owner_id
                    and document["visibility"] != "public"
                ):
                    continue
                if document["status"] == "deleted":
                    continue
                if not include_expired and _expired(document.get("expires_at")):
                    continue
                detail = self._detail_from_fake(document)
                try:
                    detail = self._public_detail(
                        detail, owner_id=owner_id, is_admin=is_admin,
                    )
                except KnowledgeNotFoundError:
                    continue
                if (
                    not include_expired
                    and detail["active_version_id"] is None
                    and not is_admin
                    and document["owner_id"] != owner_id
                ):
                    continue
                rows.append(detail)
            rows.sort(key=lambda row: (str(row.get("updated_at") or ""), str(row["id"])), reverse=True)
            return rows

        def _list(conn):
            visibility_scope = (
                "status<>'deleted'" if is_admin
                else "(owner_id=%s OR visibility='public') AND status<>'deleted'"
            )
            params: tuple[Any, ...] = () if is_admin else (owner_id,)
            rows = conn.execute(
                "SELECT id::text AS id,owner_id,name,category,visibility,status,active_version_id::text AS active_version_id,expires_at,credibility,created_at,updated_at "
                "FROM knowledge_documents WHERE " + visibility_scope + " "
                + ("" if include_expired else "AND (expires_at IS NULL OR expires_at>now())")
                + " ORDER BY updated_at DESC,id DESC",
                params,
            ).fetchall()
            details = []
            for row in rows:
                try:
                    details.append(
                        self._get_detail_pg(
                            conn, owner_id, str(row["id"]), is_admin=is_admin,
                        )
                    )
                except KnowledgeNotFoundError:
                    continue
            return details

        return self._pg(_list)

    def get_document(self, owner_id: str, document_id: str, *, is_admin: bool = False) -> dict[str, Any]:
        document_id = _validate_uuid(document_id, "document_id")
        self.recover_stale_indexing(
            None if is_admin else owner_id,
            stale_after_seconds=_STALE_INDEXING_SECONDS,
        )
        document = self._raw_document(owner_id, document_id, is_admin=is_admin)
        if self._fake:
            return self._public_detail(
                self._detail_from_fake(document), owner_id=owner_id, is_admin=is_admin,
            )

        def _read(conn):
            return self._get_detail_pg(conn, owner_id, document_id, is_admin=is_admin)

        return self._pg(_read)

    @staticmethod
    def _timestamp_is_stale(value: Any, cutoff: datetime) -> bool:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return True
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return timestamp < cutoff

    def recover_stale_indexing(
        self,
        owner_id: str | None = None,
        *,
        stale_after_seconds: int = 1800,
    ) -> dict[str, int]:
        """Close abandoned indexing leases so they cannot remain indefinite."""

        try:
            stale_after_seconds = int(stale_after_seconds)
        except (TypeError, ValueError) as exc:
            raise KnowledgeValidationError("stale_after_seconds 必须是正整数") from exc
        if stale_after_seconds < 1:
            raise KnowledgeValidationError("stale_after_seconds 必须是正整数")
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)

        if self._fake:
            recovered = failed = activated = 0
            with self.db.write_lock:
                state = self._state()
                for version in state["versions"].values():
                    if version.get("status") != "indexing":
                        continue
                    document = state["documents"].get(version["document_id"])
                    if not document or (owner_id is not None and document.get("owner_id") != owner_id):
                        continue
                    if not self._timestamp_is_stale(version.get("updated_at"), cutoff):
                        continue
                    recovered += 1
                    active = str(document.get("active_version_id") or "") == str(version["id"])
                    if active:
                        version["status"] = "active"
                        version["updated_at"] = _now()
                        self._set_governance_vector_status(
                            document["id"], version["id"], "active",
                        )
                        activated += 1
                    else:
                        version["status"] = "failed"
                        version["updated_at"] = _now()
                        for chunk in state["chunks"].values():
                            if (
                                chunk.get("version_id") == version["id"]
                                and chunk.get("index_status") != "indexed"
                            ):
                                chunk["index_status"] = "failed"
                                chunk["updated_at"] = _now()
                        self._delete_governance_vectors(
                            self._governance_vector_filters(
                                document["id"], version_id=version["id"],
                            )
                        )
                        failed += 1
            return {"recovered": recovered, "failed": failed, "activated": activated}

        def _recover(conn):
            params: list[Any] = [cutoff]
            owner_clause = ""
            if owner_id is not None:
                owner_clause = " AND d.owner_id=%s"
                params.append(owner_id)
            rows = conn.execute(
                "SELECT v.id::text AS id,v.document_id::text AS document_id,"
                "d.active_version_id::text AS active_version_id "
                "FROM knowledge_document_versions v "
                "JOIN knowledge_documents d ON d.id=v.document_id "
                "WHERE v.status='indexing' AND v.updated_at < %s"
                + owner_clause
                + " ORDER BY d.id,v.id",
                tuple(params),
            ).fetchall()
            activated_ids: list[tuple[str, str]] = []
            failed_ids: list[tuple[str, str]] = []
            for row in rows:
                version_id = str(row["id"])
                document_id = str(row["document_id"])
                # Match writers' lock order, then recheck after waiting. Recovery
                # must not act on a lease that another worker already completed.
                document = conn.execute(
                    "SELECT active_version_id::text AS active_version_id,visibility "
                    "FROM knowledge_documents WHERE id=%s FOR UPDATE", (document_id,),
                ).fetchone()
                stale = conn.execute(
                    "SELECT id FROM knowledge_document_versions WHERE id=%s "
                    "AND status='indexing' AND updated_at < %s FOR UPDATE", (version_id, cutoff),
                ).fetchone()
                if not document or not stale:
                    continue
                if str(document["active_version_id"] or "") == version_id:
                    conn.execute(
                        "UPDATE knowledge_document_versions SET status='active',updated_at=now() WHERE id=%s",
                        (version_id,),
                    )
                    activated_ids.append((document_id, version_id))
                    if self.vector_store is not None:
                        self.vector_store.set_payload_by_filter(
                            {"visibility": document["visibility"]},
                            self._governance_vector_filters(document_id, version_id=version_id),
                        )
                    self._set_governance_vector_status(document_id, version_id, "active")
                else:
                    conn.execute(
                        "UPDATE knowledge_document_versions SET status='failed',updated_at=now() WHERE id=%s",
                        (version_id,),
                    )
                    conn.execute(
                        "UPDATE knowledge_document_chunks SET index_status='failed',updated_at=now() "
                        "WHERE version_id=%s AND index_status<>'indexed'",
                        (version_id,),
                    )
                    failed_ids.append((document_id, version_id))
                    self._delete_governance_vectors(
                        self._governance_vector_filters(document_id, version_id=version_id),
                    )
            return {
                "recovered": len(failed_ids) + len(activated_ids),
                "failed": len(failed_ids),
                "activated": len(activated_ids),
            }

        return self._pg(_recover)

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
        document_id = _validate_uuid(document_id, "document_id")
        version_id = _validate_uuid(version_id, "version_id")
        self.recover_stale_indexing(owner_id)
        document = self._governable_document(owner_id, document_id, is_admin=is_admin)
        if not self._fake and indexer is None:
            raise KnowledgeIndexingError("生产知识版本重索引必须提供真实索引器")
        if self._fake:
            state = self._state()
            version = state["versions"].get(version_id)
            if not version or version["document_id"] != document_id:
                raise KnowledgeNotFoundError("知识版本不存在或无权访问")
            if _expired(version.get("expires_at")) and not allow_expired:
                raise KnowledgeValidationError("知识版本已过期，请先续期")
            chunks = sorted((c for c in state["chunks"].values() if c["version_id"] == version_id), key=lambda c: c["ordinal"])
            if not chunks:
                raise KnowledgeValidationError("知识版本至少需要一个有效分块")
            was_active = (
                str(document.get("active_version_id") or "") == version_id
                or version.get("status") == "active"
            )
            previous_indexed_at = version.get("indexed_at")
            previous_chunks = {
                chunk["id"]: {
                    "index_status": chunk.get("index_status"),
                    "qdrant_point_id": chunk.get("qdrant_point_id"),
                    "updated_at": chunk.get("updated_at"),
                }
                for chunk in chunks
            }
            old_active_version_ids = {
                str(item["id"])
                for item in state["versions"].values()
                if item["document_id"] == document_id and item.get("status") == "active"
            }
            self._retire_version_vectors(document_id, old_active_version_ids)
            version["status"] = "indexing"
            try:
                for chunk in chunks:
                    point = indexer(chunk) if indexer else f"knowledge:{version_id}:{chunk['ordinal']}"
                    chunk["qdrant_point_id"] = point or f"knowledge:{version_id}:{chunk['ordinal']}"
                    chunk["index_status"] = "indexed"
                    chunk["updated_at"] = _next_now(chunk.get("updated_at"))
            except Exception:
                version["status"] = "active" if was_active else "failed"
                if was_active:
                    version["indexed_at"] = previous_indexed_at
                    for chunk in chunks:
                        previous = previous_chunks[chunk["id"]]
                        chunk.update(previous)
                else:
                    for chunk in chunks:
                        if chunk["index_status"] != "indexed":
                            chunk["index_status"] = "failed"
                version["updated_at"] = _now()
                for old_version_id in old_active_version_ids:
                    self._set_governance_vector_status(document_id, old_version_id, "active")
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
            detail = self._detail_from_fake(document)
            self._activate_vector_projection(
                document_id, version_id, old_active_version_ids, len(chunks),
                visibility=document["visibility"],
            )
            return detail

        def _prepare(conn):
            document_row = conn.execute(
                "SELECT id::text AS id,visibility,active_version_id::text AS active_version_id "
                "FROM knowledge_documents WHERE id=%s FOR UPDATE",
                (document_id,),
            ).fetchone()
            if not document_row:
                raise KnowledgeNotFoundError("知识文档不存在或无权访问")
            version = conn.execute(
                "SELECT id::text AS id,document_id::text AS document_id,status,expires_at,indexed_at FROM knowledge_document_versions WHERE id=%s AND document_id=%s FOR UPDATE",
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
            if not chunks:
                raise KnowledgeValidationError("知识版本至少需要一个有效分块")
            old_active_version_ids = {
                str(row["id"]) for row in conn.execute(
                    "SELECT id::text AS id FROM knowledge_document_versions "
                    "WHERE document_id=%s AND status='active'",
                    (document_id,),
                ).fetchall()
            }
            conn.execute("UPDATE knowledge_document_versions SET status='indexing',updated_at=now() WHERE id=%s", (version_id,))
            return {
                "was_active": (
                    str(document_row["active_version_id"] or "") == version_id
                    or version["status"] == "active"
                ),
                "previous_indexed_at": version.get("indexed_at"),
                "chunks": chunks,
                "old_active_version_ids": old_active_version_ids,
                "visibility": document_row["visibility"],
            }

        def _mark_failure(conn, prepared):
            def _fail(conn):
                if prepared["was_active"]:
                    conn.execute(
                        "UPDATE knowledge_document_versions SET status='active',indexed_at=%s,updated_at=now() WHERE id=%s",
                        (prepared["previous_indexed_at"], version_id),
                    )
                    for chunk in prepared["chunks"]:
                        conn.execute(
                            "UPDATE knowledge_document_chunks SET index_status=%s,qdrant_point_id=%s,updated_at=now() WHERE id=%s",
                            (chunk["index_status"], chunk["qdrant_point_id"], chunk["id"]),
                        )
                else:
                    conn.execute(
                        "UPDATE knowledge_document_versions SET status='failed',updated_at=now() WHERE id=%s",
                        (version_id,),
                    )
                    conn.execute(
                        "UPDATE knowledge_document_chunks SET index_status='failed',updated_at=now() "
                        "WHERE version_id=%s AND index_status<>'indexed'",
                        (version_id,),
                    )

            return _fail(conn)

        def _finalize(conn, points):
            def _finish(conn):
                for chunk_id, point in points:
                    updated = conn.execute(
                        "UPDATE knowledge_document_chunks SET qdrant_point_id=%s,index_status='indexed',updated_at=now() WHERE id=%s AND version_id=%s",
                        (point, chunk_id, version_id),
                    )
                    if getattr(updated, "rowcount", 1) != 1:
                        raise KnowledgeNotFoundError("知识分块不存在或无权访问")
                conn.execute("UPDATE knowledge_document_versions SET status='archived',updated_at=now() WHERE document_id=%s AND status='active' AND id<>%s", (document_id, version_id))
                conn.execute("UPDATE knowledge_document_versions SET status='active',indexed_at=now(),updated_at=now() WHERE id=%s", (version_id,))
                conn.execute("UPDATE knowledge_documents SET active_version_id=%s,updated_at=now() WHERE id=%s", (version_id, document_id))
                return self._get_detail_pg(conn, owner_id, document_id, is_admin=is_admin)

            return _finish(conn)

        def _run(conn):
            # Keep the document row lock across preparation, external writes,
            # activation and commit. A process-local RLock cannot protect these
            # stable point ids from another worker's edit or reindex.
            prepared = _prepare(conn)
            points: list[tuple[str, str]] = []
            try:
                # Savepoint permits durable failure bookkeeping without releasing
                # the document lock acquired by _prepare.
                with conn.transaction():
                    self._retire_version_vectors(document_id, prepared["old_active_version_ids"])
                    for chunk in prepared["chunks"]:
                        point = indexer(chunk)
                        if not point:
                            raise KnowledgeIndexingError("索引器未返回有效的 Qdrant point id")
                        points.append((str(chunk["id"]), str(point)))
                    detail = _finalize(conn, points)
                    self._activate_vector_projection(
                        document_id, version_id, prepared["old_active_version_ids"], len(points),
                        visibility=prepared["visibility"],
                        cleanup=False,
                    )
            except Exception as exc:
                _mark_failure(conn, prepared)
                self._set_governance_vector_status(document_id, version_id, "failed")
                for old_version_id in prepared["old_active_version_ids"]:
                    if self.vector_store is not None:
                        self.vector_store.set_payload_by_filter(
                            {"visibility": prepared["visibility"]},
                            self._governance_vector_filters(document_id, version_id=old_version_id),
                        )
                    self._set_governance_vector_status(document_id, old_version_id, "active")
                return None, exc
            return detail, None

        def _reconcile_or_cleanup(conn, *, failed: bool):
            current = conn.execute(
                "SELECT active_version_id::text AS active_version_id,visibility "
                "FROM knowledge_documents WHERE id=%s FOR UPDATE", (document_id,),
            ).fetchone()
            active_id = str(current["active_version_id"] or "") if current else ""
            if failed:
                # A COMMIT error can be ambiguous. Align with durable current
                # state under lock, including any intervening edit/unpublish.
                if active_id != version_id:
                    self._set_governance_vector_status(document_id, version_id, "failed")
                if active_id:
                    if self.vector_store is not None:
                        self.vector_store.set_payload_by_filter(
                            {"visibility": current["visibility"]},
                            self._governance_vector_filters(document_id, version_id=active_id),
                        )
                    self._set_governance_vector_status(document_id, active_id, "active")
            else:
                # Physical deletion is irreversible; do it only after commit,
                # and never delete a version reactivated by a newer worker.
                archived = conn.execute(
                    "SELECT id::text AS id FROM knowledge_document_versions "
                    "WHERE document_id=%s AND status='archived' AND id<>%s",
                    (document_id, active_id or version_id),
                ).fetchall()
                for row in archived:
                    self._delete_governance_vectors(
                        self._governance_vector_filters(document_id, version_id=str(row["id"])),
                    )

        try:
            detail, failure = self._pg(_run)
        except Exception:
            self._pg(lambda conn: _reconcile_or_cleanup(conn, failed=True))
            raise
        if failure is not None:
            raise failure
        self._pg(lambda conn: _reconcile_or_cleanup(conn, failed=False))
        return detail

    def record_citations(
        self,
        owner_id: str,
        document_id: str,
        version_id: str,
        chunk_ids: list[str],
        *,
        request_id: str,
    ) -> dict[str, int]:
        document_id = _validate_uuid(document_id, "document_id")
        version_id = _validate_uuid(version_id, "version_id")
        self._raw_document(owner_id, document_id)
        request_id = str(request_id or "").strip()
        if not request_id or len(request_id) > 128:
            raise KnowledgeValidationError("request_id 无效")
        unique_ids = list(
            dict.fromkeys(_validate_uuid(value, "chunk_id") for value in chunk_ids)
        )
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
            "INSERT INTO knowledge_document_versions "
            "(id,document_id,version_number,content_sha256,size_bytes,source_content_sha256,source_size_bytes,mime_type,status,expires_at,credibility) "
            "SELECT %s,%s,COALESCE(MAX(version_number),0)+1,%s,%s,%s,%s,%s,'draft',%s,%s "
            "FROM knowledge_document_versions WHERE document_id=%s RETURNING id::text AS id,version_number",
            (
                version_id, document_id, content_sha256, size_bytes,
                content_sha256, size_bytes, mime_type or "application/octet-stream",
                expires_at, credibility, document_id,
            ),
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
            "SELECT id::text AS id,document_id::text AS document_id,version_number,content_sha256,size_bytes,source_content_sha256,source_size_bytes,mime_type,status,expires_at,credibility,indexed_at,created_at,updated_at FROM knowledge_document_versions WHERE document_id=%s ORDER BY version_number DESC",
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
        return KnowledgeGovernance._public_detail(
            _safe(document), owner_id=owner_id, is_admin=is_admin,
        )

    @staticmethod
    def _public_detail(
        detail: dict[str, Any], *, owner_id: str, is_admin: bool = False,
    ) -> dict[str, Any]:
        """Hide governance history and vector internals from public readers."""

        if is_admin or str(detail.get("owner_id") or "") == str(owner_id):
            return detail
        if detail.get("visibility") != "public" or detail.get("status") in {"deleted", "expired"}:
            raise KnowledgeNotFoundError("知识文档不存在或无权访问")
        active_id = str(detail.get("active_version_id") or "")
        active = next(
            (
                version for version in detail.get("versions", [])
                if str(version.get("id") or "") == active_id and version.get("status") == "active"
            ),
            None,
        )
        if active is None or _expired(active.get("expires_at")):
            raise KnowledgeNotFoundError("知识文档不存在或无权访问")
        visible_chunks = []
        for chunk in active.get("chunks", []):
            if chunk.get("index_status") != "indexed":
                continue
            visible_chunks.append({
                key: chunk.get(key)
                for key in ("id", "ordinal", "page", "text", "index_status")
            })
        visible_version = {
            key: active.get(key)
            for key in (
                "id", "version_number", "status", "expires_at", "credibility",
                "indexed_at", "citation_hits",
            )
        }
        visible_version["chunks"] = visible_chunks
        visible = {
            key: detail.get(key)
            for key in (
                "id", "name", "category", "visibility", "status", "active_version_id",
                "expires_at", "credibility", "citation_hits",
            )
        }
        visible["versions"] = [visible_version]
        return _safe(visible)


__all__ = [
    "KnowledgeGovernance", "KnowledgeGovernanceError", "KnowledgeNotFoundError",
    "KnowledgePermissionError", "KnowledgeConflictError", "KnowledgeIndexingError",
    "KnowledgeValidationError",
]
