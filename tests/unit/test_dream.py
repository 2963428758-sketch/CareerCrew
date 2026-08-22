"""Auto Dream 调度单测：schedule 解析 / 到点判定 / 全量跑一轮的计数与容错。"""
from __future__ import annotations

from datetime import datetime

from careercrew_api.dream import dream_due, parse_schedule, run_dream_cycle


def test_parse_schedule() -> None:
    assert parse_schedule("off") is None
    assert parse_schedule("") is None
    assert parse_schedule(None) is None
    assert parse_schedule("04:30") == (4, 30)
    assert parse_schedule("23:59") == (23, 59)
    assert parse_schedule("24:00") is None  # 越界
    assert parse_schedule("bad") is None
    assert parse_schedule("4:30") == (4, 30)  # 宽松接受 H:MM


def test_dream_due() -> None:
    hhmm = (4, 30)
    assert dream_due(datetime(2026, 8, 22, 4, 29), hhmm, "") is False
    assert dream_due(datetime(2026, 8, 22, 4, 30), hhmm, "") is True
    assert dream_due(datetime(2026, 8, 22, 23, 0), hhmm, "") is True
    # 当日已跑过不重复触发；次日恢复
    assert dream_due(datetime(2026, 8, 22, 23, 0), hhmm, "2026-08-22") is False
    assert dream_due(datetime(2026, 8, 23, 4, 30), hhmm, "2026-08-22") is True


class _FakeRt:
    def __init__(self, results: dict):
        self._results = results
        self.calls: list[str] = []

    def memory_consolidate(self, user_id: str) -> dict:
        self.calls.append(user_id)
        return self._results[user_id]


class _FakeStore:
    def __init__(self, accounts: list[dict]):
        self._accounts = accounts

    def list_accounts(self, offset: int, limit: int):
        return self._accounts, len(self._accounts)


class _FakeAuth:
    def __init__(self, accounts: list[dict]):
        self.store = _FakeStore(accounts)


def test_run_dream_cycle_counts() -> None:
    rt = _FakeRt({
        "u1": {"ran": True, "phases": ["orient"]},
        "u2": {"ran": False, "reason": "gate_not_met"},
    })
    auth = _FakeAuth([{"id": "u1"}, {"id": "u2"}])
    stats = run_dream_cycle(rt, auth, now=datetime(2026, 8, 22, 4, 30))
    assert stats == {"ran": 1, "skipped": 1, "failed": 0}
    assert rt.calls == ["u1", "u2"]


def test_run_dream_cycle_failure_does_not_abort() -> None:
    class FailingRt(_FakeRt):
        def memory_consolidate(self, user_id: str) -> dict:
            if user_id == "bad":
                raise RuntimeError("boom")
            return {"ran": True}

    rt = FailingRt({})
    auth = _FakeAuth([{"id": "bad"}, {"id": "ok"}])
    stats = run_dream_cycle(rt, auth, now=datetime(2026, 8, 22, 4, 30))
    assert stats["ran"] == 1 and stats["failed"] == 1


def test_run_dream_cycle_list_accounts_error() -> None:
    class BrokenAuth:
        class _Store:
            def list_accounts(self, offset: int, limit: int):
                raise RuntimeError("db down")

        store = _Store()

    stats = run_dream_cycle(_FakeRt({}), BrokenAuth(), now=datetime(2026, 8, 22))
    assert stats == {"ran": 0, "skipped": 0, "failed": 0, "error": "list_accounts"}
