"""第五期上传任务持久化的租户隔离、租约和故障恢复测试。"""
from __future__ import annotations

import time

from careercrew_core import upload_tasks
from careercrew_core.upload_tasks import UploadTaskStore


class _Result:
    def __init__(self, row=None, rowcount: int = 0):
        self._row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, pool):
        self.pool = pool

    def __enter__(self):
        self.pool.connection_attempts += 1
        if self.pool.failures_remaining:
            self.pool.failures_remaining -= 1
            raise OSError("postgres unavailable")
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.pool.executed.append((" ".join(sql.split()), tuple(params)))
        return _Result(self.pool.row, self.pool.rowcount)


class _Pool:
    def __init__(self, *, row=None, rowcount: int = 1, failures: int = 0):
        self.row = row
        self.rowcount = rowcount
        self.failures_remaining = failures
        self.connection_attempts = 0
        self.executed = []

    def connection(self, timeout):
        assert timeout > 0
        return _Connection(self)


def _row(**overrides):
    row = {
        "id": "job-1",
        "owner_id": "user-1",
        "kind": "resume_parse",
        "filename": "resume.pdf",
        "status": "done",
        "stage": "done",
        "progress": 1.0,
        "error": None,
        "result": '{"resume_id":"r-1"}',
        "attempts": 1,
        "lease_expires_at": None,
        "created_at": "2026-09-08T00:00:00+00:00",
        "updated_at": "2026-09-08T00:01:00+00:00",
    }
    row.update(overrides)
    return row


def test_create_assigns_a_lease_to_queued_task():
    """创建后进程若退出，租约到期才能把 queued 解释为中断。"""
    pool = _Pool()
    store = UploadTaskStore(pool=pool)

    store.create("job-1", "user-1", "resume_parse", "resume.pdf")

    sql, params = pool.executed[-1]
    assert "lease_expires_at" in sql
    assert params[:4] == ("job-1", "user-1", "resume_parse", "resume.pdf")


def test_get_is_owner_and_kind_scoped_and_normalizes_public_contract():
    """跨 worker 回源仍返回内存任务同形数据，查询本身绑定账号和任务类型。"""
    pool = _Pool(row=_row())
    store = UploadTaskStore(pool=pool)

    task = store.get("job-1", "user-1", "resume_parse")

    assert task is not None
    assert task["job_id"] == "job-1"
    assert task["user_id"] == "user-1"
    assert task["result"] == {"resume_id": "r-1"}
    assert pool.executed[-1][1] == ("job-1", "user-1", "resume_parse")


def test_update_is_owner_and_kind_scoped_and_terminal_state_clears_lease():
    """一个上传端点不能更新另一个账号或另一类任务，终态不保留活跃租约。"""
    pool = _Pool()
    store = UploadTaskStore(pool=pool)

    store.update(
        "job-1", "user-1", "resume_parse",
        status="done", stage="done", progress=1.0, result={"ok": True},
    )

    sql, params = pool.executed[-1]
    assert "lease_expires_at = NULL" in sql
    assert params[-3:] == ("job-1", "user-1", "resume_parse")


def test_mark_interrupted_only_targets_expired_leases():
    """新 worker 启动只收口过期任务，不能把其他 worker 的新鲜租约错杀。"""
    pool = _Pool(rowcount=2)
    store = UploadTaskStore(pool=pool)

    assert store.mark_interrupted() == 2

    sql, _params = pool.executed[-1]
    assert "lease_expires_at < CURRENT_TIMESTAMP" in sql
    assert "lease_expires_at IS NULL" not in sql
    assert "status IN ('queued','running')" in sql


def test_heartbeat_extends_only_the_scoped_active_task():
    """心跳续约同账号同类型活动任务，并接管 start 短暂失败留下的 queued 行。"""
    pool = _Pool()
    store = UploadTaskStore(pool=pool)

    store.heartbeat("job-1", "user-1", "resume_parse")

    sql, params = pool.executed[-1]
    assert "lease_expires_at" in sql
    assert "SET status='running'" in sql
    assert "status IN ('queued','running')" in sql
    assert "CASE WHEN status='queued' THEN 1 ELSE 0 END" in sql
    assert params[-3:] == ("job-1", "user-1", "resume_parse")


def test_heartbeat_recovers_queued_row_after_start_connection_failure():
    """create 已成功而 start 短时失败时，下一次心跳能原子接管 queued 行。"""
    pool = _Pool(rowcount=1)
    store = UploadTaskStore(pool=pool)
    store.create("job-1", "user-1", "resume_parse", "resume.pdf")
    pool.failures_remaining = 1

    store.start("job-1", "user-1", "resume_parse")
    store.heartbeat("job-1", "user-1", "resume_parse")

    sql, params = pool.executed[-1]
    assert "SET status='running'" in sql
    assert "status IN ('queued','running')" in sql
    assert "CASE WHEN status='queued' THEN 1 ELSE 0 END" in sql
    assert params[-3:] == ("job-1", "user-1", "resume_parse")


def test_lease_context_keeps_heartbeat_until_work_finishes():
    """长时间解析即使没有进度回调，也会独立续约并在退出时停止。"""
    class Store:
        def __init__(self):
            self.started = []
            self.beats = 0

        def start(self, job_id, owner_id, kind):
            self.started.append((job_id, owner_id, kind))

        def heartbeat(self, job_id, owner_id, kind):
            assert (job_id, owner_id, kind) == ("job-1", "user-1", "resume_parse")
            self.beats += 1

    store = Store()
    with upload_tasks.maintain_upload_lease(
        store, "job-1", "user-1", "resume_parse", heartbeat_interval_s=0.01,
    ):
        deadline = time.time() + 0.5
        while store.beats == 0 and time.time() < deadline:
            time.sleep(0.005)

    beats_after_exit = store.beats
    time.sleep(0.03)
    assert store.started == [("job-1", "user-1", "resume_parse")]
    assert beats_after_exit >= 1
    assert store.beats == beats_after_exit


def test_breaker_retries_after_cooldown(monkeypatch):
    """三次数据库失败后的熔断不是永久关闭，冷却期后会真实探测一次。"""
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    pool = _Pool(failures=3)
    store = UploadTaskStore(pool=pool)

    for i in range(3):
        store.create(f"job-{i}", "user-1", "resume_parse", "resume.pdf")
    assert pool.connection_attempts == 3

    now[0] += store._BREAKER_COOLDOWN_S + 1
    store.create("job-recovery", "user-1", "resume_parse", "resume.pdf")

    assert pool.connection_attempts == 4


def test_transition_backfills_task_after_initial_create_failure():
    """首次 INSERT 失败后，数据库恢复时状态转换会补建记录，而非永久停留在内存。"""
    pool = _Pool(rowcount=0, failures=1)
    store = UploadTaskStore(pool=pool)

    store.create("job-recovery", "user-1", "resume_parse", "resume.pdf")
    store.update(
        "job-recovery", "user-1", "resume_parse",
        status="done", stage="done", progress=1.0, result={"resume_id": "r-1"},
    )

    inserts = [(sql, params) for sql, params in pool.executed
               if sql.startswith("INSERT INTO upload_tasks")]
    assert len(inserts) == 1
    sql, params = inserts[0]
    assert "ON CONFLICT (id) DO NOTHING" in sql
    assert params[:3] == ("job-recovery", "user-1", "resume_parse")
    assert "done" in params


def test_app_startup_recovers_only_expired_upload_tasks(monkeypatch):
    """应用启动会调用 store 的过期租约收口，而不是清空全部 running 任务。"""
    from careercrew_api import main

    class Store:
        def __init__(self):
            self.calls = 0

        def mark_interrupted(self):
            self.calls += 1
            return 2

    store = Store()
    monkeypatch.setattr(upload_tasks, "get_upload_task_store", lambda: store)

    assert main._recover_interrupted_upload_tasks() == 2
    assert store.calls == 1
