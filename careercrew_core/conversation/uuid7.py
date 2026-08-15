"""UUIDv7（RFC 9562 风格）生成器。

Python 3.12 无内置 uuid7，自行实现：48bit Unix 毫秒时间戳 + 随机其余位
（version=7，variant=0b10）。按 RFC 9562 method B 语义进程内单调（同一毫秒
内单调递增），满足可排序 + 数据库索引局部性；跨进程不保证唯一（随机部分
即可，按 brief 约束）。线程安全（锁保护单调计数）。
"""
from __future__ import annotations

import os
import threading
import time
from uuid import UUID

_lock = threading.Lock()
_last_ms = -1
_last_tail = -1


def uuid7() -> UUID:
    """生成一个 UUIDv7（48bit Unix 毫秒时间戳 + 80bit 随机尾，进程内单调）。"""
    global _last_ms, _last_tail
    ms = int(time.time() * 1000) & ((1 << 48) - 1)   # 48bit Unix 毫秒时间戳
    with _lock:
        if ms == _last_ms:
            # 同一毫秒内：上一个随机尾 +1（单调），保证可排序且不重复
            tail = (_last_tail + 1) & ((1 << 80) - 1)
        else:
            tail = int.from_bytes(os.urandom(10), "big")   # 80bit 随机尾
        _last_ms, _last_tail = ms, tail
    value = (ms << 80) | tail
    value &= ~(0xF << 76)   # 清 version 位
    value |= (7 << 76)      # version = 7
    value &= ~(0x3 << 62)   # 清 variant 位
    value |= (0x2 << 62)    # variant = 0b10（RFC 4122）
    return UUID(int=value)
