"""上传任务持久化（第五期 P0）。

简历解析 / 知识库摄取的任务状态此前只存在于 API 进程内存字典中：
重启即丢失、多 worker 互不可见。本模块把任务状态写入 PostgreSQL
（迁移 0008 的 upload_tasks 表），执行仍在接收请求的进程内进行。

写入采用「尽力而为」：存储不可用（未配置 DSN / 表未建 / 测试环境）时
静默降级为纯内存模式，不影响主流程；GET 状态先查内存再回源数据库。
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from functools import lru_cache

from careercrew_core.pg_pool import get_shared_pool

_TASK_COLUMNS = (
    "id, owner_id, kind, filename, status, stage, progress, error, result, "
    "attempts, lease_expires_at, created_at, updated_at"
)

_LEASE_SECONDS = max(int(os.environ.get("UPLOAD_TASK_LEASE_SECONDS", "90") or "90"), 15)
_HEARTBEAT_SECONDS = max(
    float(os.environ.get("UPLOAD_TASK_HEARTBEAT_SECONDS", "20") or "20"), 1.0,
)
_INTERRUPTED_ERROR = "任务因服务中断未完成，请重新上传"


def _public(row) -> dict | None:
    if row is None:
        return None
    out = {}
    for key, value in dict(row).items():
        if key == "result" and isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        out[key] = value
    # 与原进程内任务字典保持相同的 API 字段，避免不同 worker 返回两套契约。
    out["job_id"] = out.pop("id")
    out["user_id"] = out.pop("owner_id")
    return out


class UploadTaskStore:
    """尽力而为的持久化：连接/写入失败时快速降级（短超时 + 60s 熔断），
    绝不阻塞上传解析主流程——内存字典始终是第一真相源。"""

    _DB_TIMEOUT_S = 2.0
    _BREAKER_COOLDOWN_S = 60.0
    _BREAKER_THRESHOLD = 3

    def __init__(self, dsn: str = "", *, pool=None):
        if pool is None and not dsn.strip():
            raise ValueError("上传任务存储需要 DATABASE_URL")
        self.pool = pool if pool is not None else get_shared_pool(dsn)
        self._consecutive_failures = 0
        self._disabled_until = 0.0
        self._breaker_lock = threading.Lock()

    def _available(self) -> bool:
        now = time.time()
        with self._breaker_lock:
            if now < self._disabled_until:
                return False
            if self._disabled_until:
                # 冷却期结束后允许重新探测；旧实现保留 failure=3，导致永久熔断。
                self._disabled_until = 0.0
                self._consecutive_failures = 0
            return self._consecutive_failures < self._BREAKER_THRESHOLD

    def _record_failure(self) -> None:
        with self._breaker_lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._BREAKER_THRESHOLD:
                self._disabled_until = time.time() + self._BREAKER_COOLDOWN_S

    def _record_success(self) -> None:
        with self._breaker_lock:
            self._consecutive_failures = 0
            self._disabled_until = 0.0

    @staticmethod
    def _insert_missing_transition(conn, job_id: str, owner_id: str, kind: str,
                                   updates: dict, *, attempts: int = 0) -> None:
        """Backfill a task missed during a short DB outage without touching an ID
        that already belongs to another owner or task kind."""
        status = str(updates.get("status") or "queued")
        stage = str(updates.get("stage") or status)
        progress = float(updates.get("progress") or 0.0)
        error = updates.get("error")
        result = updates.get("result")
        result_json = json.dumps(result, ensure_ascii=False) if result is not None else None
        terminal = status in ("done", "error")
        conn.execute(
            """INSERT INTO upload_tasks
               (id, owner_id, kind, filename, status, stage, progress, error, result,
                attempts, lease_expires_at)
               VALUES (%s,%s,%s,'',%s,%s,%s,%s,%s::jsonb,%s,
                       CASE WHEN %s THEN NULL
                            ELSE CURRENT_TIMESTAMP + (%s * INTERVAL '1 second') END)
               ON CONFLICT (id) DO NOTHING""",
            (job_id, owner_id, kind, status, stage, progress, error, result_json,
             attempts, terminal, _LEASE_SECONDS),
        )

    def create(self, job_id: str, owner_id: str, kind: str, filename: str) -> None:
        if not self._available():
            return
        try:
            with self.pool.connection(timeout=self._DB_TIMEOUT_S) as conn:
                conn.execute(
                    """INSERT INTO upload_tasks (
                           id, owner_id, kind, filename, status, stage, progress, lease_expires_at
                       ) VALUES (
                           %s,%s,%s,%s,'queued','queued',0,
                           CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')
                       )
                       ON CONFLICT (id) DO NOTHING""",
                    (job_id, owner_id, kind, filename, _LEASE_SECONDS),
                )
            self._record_success()
        except Exception:  # noqa: BLE001 - 持久化失败快速降级
            self._record_failure()

    def start(self, job_id: str, owner_id: str, kind: str) -> None:
        """开始执行并取得租约；attempts 只在每次真实执行开始时增加。"""
        if not self._available():
            return
        try:
            with self.pool.connection(timeout=self._DB_TIMEOUT_S) as conn:
                result = conn.execute(
                    """UPDATE upload_tasks
                       SET status='running', attempts=attempts+1,
                           lease_expires_at=CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                           updated_at=CURRENT_TIMESTAMP
                       WHERE id=%s AND owner_id=%s AND kind=%s
                         AND status IN ('queued','running')""",
                    (_LEASE_SECONDS, job_id, owner_id, kind),
                )
                if int(result.rowcount or 0) == 0:
                    self._insert_missing_transition(
                        conn, job_id, owner_id, kind,
                        {"status": "running", "stage": "running", "progress": 0.0},
                        attempts=1,
                    )
            self._record_success()
        except Exception:  # noqa: BLE001 - 执行仍可在进程内继续
            self._record_failure()

    def heartbeat(self, job_id: str, owner_id: str, kind: str) -> None:
        """续约仍在运行的同租户同类型任务。"""
        if not self._available():
            return
        try:
            with self.pool.connection(timeout=self._DB_TIMEOUT_S) as conn:
                result = conn.execute(
                    """UPDATE upload_tasks
                       SET status='running',
                           attempts=attempts + CASE WHEN status='queued' THEN 1 ELSE 0 END,
                           lease_expires_at=CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                           updated_at=CURRENT_TIMESTAMP
                       WHERE id=%s AND owner_id=%s AND kind=%s
                         AND status IN ('queued','running')""",
                    (_LEASE_SECONDS, job_id, owner_id, kind),
                )
                if int(result.rowcount or 0) == 0:
                    self._insert_missing_transition(
                        conn, job_id, owner_id, kind,
                        {"status": "running", "stage": "running", "progress": 0.0},
                        attempts=1,
                    )
            self._record_success()
        except Exception:  # noqa: BLE001 - 心跳失败时当前解析仍继续
            self._record_failure()

    def update(self, job_id: str, owner_id: str, kind: str, **updates) -> None:
        """增量更新任务状态字段（status/stage/progress/error/result）。"""
        fields: list[str] = []
        params: list[object] = []
        for key in ("status", "stage", "progress", "error"):
            if key in updates:
                fields.append(f"{key} = %s")
                params.append(updates[key])
        if "result" in updates:
            fields.append("result = %s::jsonb")
            params.append(json.dumps(updates["result"], ensure_ascii=False)
                          if updates["result"] is not None else None)
        if updates.get("status") in ("done", "error"):
            fields.append("lease_expires_at = NULL")
        if not fields:
            return
        if not self._available():
            return
        params.extend([job_id, owner_id, kind])
        try:
            with self.pool.connection(timeout=self._DB_TIMEOUT_S) as conn:
                result = conn.execute(
                    f"UPDATE upload_tasks SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP "  # noqa: S608 -- fields is an internal allow-list
                    "WHERE id = %s AND owner_id = %s AND kind = %s",
                    params,
                )
                if int(result.rowcount or 0) == 0:
                    self._insert_missing_transition(
                        conn, job_id, owner_id, kind, updates,
                    )
            self._record_success()
        except Exception:  # noqa: BLE001 - 持久化失败快速降级
            self._record_failure()

    def get(self, job_id: str, owner_id: str, kind: str) -> dict | None:
        if not self._available():
            return None
        try:
            with self.pool.connection(timeout=self._DB_TIMEOUT_S) as conn:
                # 查询时同步收口该任务，保证错过启动恢复时也不会永久 running。
                conn.execute(
                    """UPDATE upload_tasks
                       SET status='error', stage='interrupted', error=%s,
                           lease_expires_at=NULL, updated_at=CURRENT_TIMESTAMP
                       WHERE id=%s AND owner_id=%s AND kind=%s
                         AND status IN ('queued','running')
                         AND lease_expires_at < CURRENT_TIMESTAMP""",
                    (_INTERRUPTED_ERROR, job_id, owner_id, kind),
                )
                row = conn.execute(
                    f"SELECT {_TASK_COLUMNS} FROM upload_tasks "  # noqa: S608 -- fixed internal column list
                    "WHERE id = %s AND owner_id = %s AND kind = %s",
                    (job_id, owner_id, kind),
                ).fetchone()
            self._record_success()
            return _public(row)
        except Exception:  # noqa: BLE001 - 回源失败按不存在处理
            self._record_failure()
            return None

    def mark_interrupted(self) -> int:
        """收口所有租约已经过期的活动任务；新鲜租约属于其他 worker，绝不触碰。"""
        if not self._available():
            return 0
        try:
            with self.pool.connection(timeout=self._DB_TIMEOUT_S) as conn:
                result = conn.execute(
                    """UPDATE upload_tasks
                       SET status='error', stage='interrupted', error=%s,
                           lease_expires_at=NULL, updated_at=CURRENT_TIMESTAMP
                       WHERE status IN ('queued','running')
                         AND lease_expires_at < CURRENT_TIMESTAMP""",
                    (_INTERRUPTED_ERROR,),
                )
                count = int(result.rowcount or 0)
            self._record_success()
            return count
        except Exception:  # noqa: BLE001 - 启动恢复失败不能阻止 API 启动
            self._record_failure()
            return 0


@contextmanager
def maintain_upload_lease(store, job_id: str, owner_id: str, kind: str, *,
                          heartbeat_interval_s: float = _HEARTBEAT_SECONDS):
    """在解析线程存活期间独立续约，避免长解析没有进度回调时租约过期。"""
    if store is None:
        yield
        return

    stop = threading.Event()
    store.start(job_id, owner_id, kind)

    def _heartbeat_loop() -> None:
        while not stop.wait(heartbeat_interval_s):
            try:
                store.heartbeat(job_id, owner_id, kind)
            except Exception:  # noqa: BLE001, S112 - 心跳失败由 store 熔断记录，不能打断任务
                continue

    thread = threading.Thread(
        target=_heartbeat_loop, name=f"upload-lease-{job_id}", daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=min(max(heartbeat_interval_s, 0.1), 1.0))


@lru_cache(maxsize=1)
def get_upload_task_store():
    """进程级共享 store（按 DSN 惰性创建）；未配置 DSN 时返回 None（纯内存降级）。"""
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        return None
    try:
        return UploadTaskStore(dsn)
    except Exception:  # noqa: BLE001 - 存储不可用时降级为内存模式
        return None
