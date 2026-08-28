
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:

    pass


pass




def _norm_path(p: str) -> str:
    return str(p).replace("\\", "/").lower()


def _capture_langsmith_run_id() -> str | None:
    """取当前 LangSmith 根 run id（tracing 关闭时为 None）。

    仅在 traced 上下文内有效：traced_call 包住 impl 后，get_current_run_tree()
    返回当前 run 树；tracing 未启用 get_current_run_tree() 仍可安全调用（返回 None）。
    """
    try:
        from langsmith import get_current_run_tree

        tree = get_current_run_tree()
        return str(tree.id) if tree is not None else None
    except Exception:  # noqa: BLE001 - 埋点失败不影响主链路
        return None


def _observability_from_result(result) -> dict:
    """从 AgentResult 抽取观测字段（tokens + tool_call 明细）。

    返回 {input_tokens, output_tokens, total_tokens, tool_calls}；result 为 None
    或缺新字段时相应值为 None / []（静默降级，不阻塞收尾）。
    """
    if result is None:
        return {
            "input_tokens": None, "output_tokens": None, "total_tokens": None,
            "tool_calls": [],
        }
    input_tokens = getattr(result, "input_tokens", None)
    output_tokens = getattr(result, "output_tokens", None)
    total_tokens = None
    if input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    details = getattr(result, "tool_call_details", None) or []
    tool_calls = []
    for d in details:
        err = d.get("error")
        error_type = None
        if err:
            error_type = str(err).split(":", 1)[0] or None
        tool_calls.append({
            "tool_name": str(d.get("name") or ""),
            "input_redacted": d.get("args"),
            "output_summary": None,
            "status": "failed" if err else "completed",
            "duration_ms": d.get("duration_ms"),
            "error_type": error_type,
            "error_summary": err,
        })
    # T3.5 §16.4 HITL：被拦截（未执行）的调用作为独立 tool_call 行落库，
    # status=awaiting_confirmation + hitl_status=pending（block-and-record，无恢复执行）。
    # 这些调用在 HitlMiddleware.wrap_tool_call 被短路，未进入 Observability 明细，
    # 改由 AgentResult.blocked_tool_calls 承载。
    for b in getattr(result, "blocked_tool_calls", None) or []:
        tool_calls.append({
            "tool_name": str(b.get("name") or ""),
            "input_redacted": b.get("args"),
            "output_summary": None,
            "status": "awaiting_confirmation",
            "duration_ms": None,
            "requires_hitl": True,
            "hitl_status": "pending",
            "error_type": None,
            "error_summary": None,
        })
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "tool_calls": tool_calls,
    }


def _rag_query_retrievals(tool_call_details: list[dict], start_index: int = 0) -> list[dict]:
    """从 tool_call_details 里 name=="rag_query" 的条目生成 retrieval 行（尽力而为）。

    无法从工具结果拿到 doc/chunk id 与 score（rag_query 返回纯文本），此处只落
    query_text_redacted（args 摘要）+ scope；document_id/chunk_id/recall_score 为空。
    """
    retrievals: list[dict] = []
    idx = start_index
    for d in tool_call_details or []:
        if d.get("name") != "rag_query":
            continue
        args = d.get("args") or {}
        q = args.get("query") if isinstance(args, dict) else None
        retrievals.append({
            "query_index": idx,
            "query_text_redacted": str(q) if q else None,
            "scope": None,
            "document_id": None,
            "chunk_id": None,
            "recall_score": None,
            "used_in_final_context": False,
            # 非 sink 观测路径的 rag_query 均为 Agent 自动检索（无强制上下文），
            # 显式标 'auto'，不依赖 finish_turn 的默认值兜底。
            "retrieval_source": "auto",
        })
        idx += 1
    return retrievals


def _read_image_paths(result) -> set[str]:
    """agent 实际 read_image 过的图片路径（这些来源确实被用来作答）。"""
    paths: set[str] = set()
    for it in getattr(result, "iterations", None) or []:
        for tc in getattr(it, "tool_calls", None) or []:
            if tc.get("name") == "read_image":
                p = (tc.get("args") or {}).get("image_path")
                if p:
                    paths.add(_norm_path(p))
    return paths


def _cap_sources(
    sources: list[dict],
    limit: int = 3,
    min_score: float = 0.0,
    keep_paths: set[str] | None = None,
) -> list[dict]:
    """知识库问答来源收敛：按分数降序取前 limit 条（默认 top-3）。

    低相关度（score < min_score）的来源不展示，除非它的图片被 agent
    实际 read_image 读过（该来源确实支撑了回答，标记 used_image=True）。
    """
    keep = keep_paths or set()
    kept: list[dict] = []
    for s in sources:
        score = float(s.get("score") or 0.0)
        img = _norm_path(s.get("image_path") or "")
        if img and img in keep:
            kept.append({**s, "used_image": True})
        elif score >= min_score:
            kept.append({**s, "used_image": False})
    kept.sort(key=lambda s: float(s.get("score") or 0.0), reverse=True)
    return kept[:limit]


class RuntimeInitError(RuntimeError):
    """运行时初始化失败（重组件加载 / 向量库连接失败等），应映射为 503。"""


class ResourceNotFoundError(LookupError):
    """Authenticated tenant does not own the requested resource."""


class RegenerateConflictError(Exception):
    """regenerate 前置校验失败（非 assistant / 非 completed / 非最后一条 / 不支持的模块）。

    路由映射为 409（区别于 ResourceNotFoundError 的 404）。
    """


logger = logging.getLogger(__name__)
