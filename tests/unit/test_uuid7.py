"""uuid7（RFC 9562 风格）单元测试。"""
from __future__ import annotations

import time
from uuid import UUID

from careercrew_core.conversation.uuid7 import uuid7


def test_version_is_7():
    u = UUID(str(uuid7()))
    assert u.version == 7


def test_string_length_and_format():
    s = str(uuid7())
    assert len(s) == 36  # 标准 8-4-4-4-12
    assert s.count("-") == 4
    UUID(s)  # 可被解析，不抛异常


def test_time_prefix_sortable():
    """生成的 uuid 按生成顺序可排序（时间前缀单调）。"""
    ids = [uuid7() for _ in range(100)]
    assert ids == sorted(ids)


def test_time_prefix_encodes_now():
    """48bit unix 毫秒时间戳前缀接近当前时间。"""
    now_ms = int(time.time() * 1000)
    ts_ms = UUID(str(uuid7())).int >> 80
    assert abs(now_ms - ts_ms) < 10_000  # 10 秒容差


def test_uniqueness():
    n = 1000
    ids = {str(uuid7()) for _ in range(n)}
    assert len(ids) == n
