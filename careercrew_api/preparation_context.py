"""r-prep- / i-prep- 准备会话的岗位上下文（独立于模型与记忆运行时）。

resume / interview 路由遇到前缀线程时按当前用户加载会话快照，把固定 JD + 简历
版本注入每一轮（含 regenerate）；会话缺失或模块不匹配一律 404，普通线程零影响。
"""
from __future__ import annotations

from fastapi import HTTPException

from careercrew_core.preparation.store import PreparationStore

# 与 PreparationStore.create_session 的前缀约定保持一致
PREPARED_PREFIXES = ("r-prep-", "i-prep-")


def is_prepared_thread(thread_id: str) -> bool:
    return any(str(thread_id or "").startswith(prefix) for prefix in PREPARED_PREFIXES)


def get_preparation_store() -> PreparationStore:
    import os

    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise HTTPException(status_code=503, detail="岗位准备存储尚未配置")
    return PreparationStore(dsn)


def load_prepared_session(owner_id: str, thread_id: str) -> dict | None:
    """静默加载（供 regenerate 兜底等非 HTTP 路径）：失败/缺失返回 None。"""
    try:
        return get_preparation_store().get_session(owner_id, thread_id)
    except Exception:  # noqa: BLE001
        return None


def load_prepared_or_404(owner_id: str, thread_id: str, module: str) -> dict:
    """加载当前用户在指定线程上的准备会话；缺失/跨账号/模块不匹配统一 404。"""
    try:
        session = get_preparation_store().get_session(owner_id, thread_id)
    except HTTPException:
        raise
    except Exception as err:  # noqa: BLE001 - 存储故障按未配置处理，不阻断普通对话路径
        raise HTTPException(status_code=503, detail="岗位准备存储暂时不可用") from err
    if session is None or session.get("module") != module:
        raise HTTPException(status_code=404, detail="岗位、简历版本或准备会话不存在")
    return session


def prepared_context_block(session: dict) -> str:
    """把会话快照格式化为每轮注入的数据上下文（保持用户问题可读）。"""
    return (
        f"【目标岗位】{session.get('company', '')} · {session.get('title', '')}\n"
        f"【岗位 JD】\n{session.get('jd', '')}\n\n"
        f"【候选人简历版本】{session.get('resume_label', '')}\n"
        f"{session.get('resume_content', '')}"
    )
