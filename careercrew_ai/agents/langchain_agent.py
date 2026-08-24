"""LangChain 1.x ``create_agent`` 组装 + 流式适配（AGENT_LANGSMITH_SPEC Part A）。

替换手写 ReAct 循环：agent 执行链（LLM 调用 / 工具调用 / 循环控制 / 流式事件）
由 LangGraph 平台提供，逐轮明细交给 LangSmith（Part B）。

对外契约（与旧 ReactLoop 对齐）：
- ``AgentResult.{content, stopped_reason, tool_calls_total, iterations}``
- 轻量 ``ReactIteration``（iteration / content / tool_calls / tool_results）

max_iterations 用 middleware 实现（``before_model`` 计数 + ``wrap_model_call`` 短路），
不依赖 recursion_limit 崩溃路径（实测 langgraph 1.2.10 超限抛 ``KeyError 'model'``，
不是稳定信号）；``recursion_limit`` 只设安全兜底。
工具执行异常由 ``wrap_tool_call`` 捕获并转 ``ToolMessage("Error: ...")`` 回喂 LLM
（实测 create_agent 默认 ToolNode 不吞异常，直接抛出，与旧循环行为不一致，需中间件补齐）。
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, NotRequired, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.graph import add_messages

MAX_ITERATIONS_MARKER = "careercrew_max_iterations_reached"
_MAX_ITERATIONS_PROMPT = "（已达最大迭代轮次）"

logger = logging.getLogger(__name__)


class AgentExecState(TypedDict):
    """create_agent 私有状态：只承载 messages 与迭代计数通道。"""

    messages: Annotated[list[AnyMessage], add_messages]
    _it: NotRequired[int]


@dataclass
class ReactIteration:
    """单轮迭代轻量记录（明细过程在 LangSmith 里）。"""

    iteration: int
    content: str  # 模型文本输出（thought）
    tool_calls: list[dict] = field(default_factory=list)  # 本轮 tool_calls（空=最终答案）
    tool_results: list[Any] = field(default_factory=list)  # 本轮工具执行结果（含错误回喂）


@dataclass
class AgentResult:
    """ReAct 循环产出（契约不变）。

    新增观测字段（T1.4，可 None / 空，向后兼容）：
    - input_tokens/output_tokens：LLM usage_metadata 累计（无 usage 时为 None）
    - tool_call_details：per-tool 明细 [{name, args, duration_ms, error}, ...]
    """

    content: str
    iterations: list[ReactIteration]
    tool_calls_total: int
    stopped_reason: str  # final_answer | max_iterations | error
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_call_details: list[dict] = field(default_factory=list)
    # T3.5 HITL：被拦截（awaiting_confirmation）的工具调用明细
    blocked_tool_calls: list[dict] = field(default_factory=list)


class MaxIterationsMiddleware(AgentMiddleware):
    """迭代上限：before_model 递增 _it，wrap_model_call 超限短路。"""

    def __init__(self, max_iters: int) -> None:
        super().__init__()
        self.max_iters = max_iters
        # 工具结果体积上限（字符）：rag_query 等检索工具的返回会作为 ToolMessage
        # 常驻后续所有迭代的上下文，无上限时单次 run 可膨胀至数十万真实 token。
        # 保留头尾：头是正文要点，尾常是图片引用行。
        self.tool_result_max_chars = int(os.environ.get("TOOL_RESULT_MAX_CHARS", "6000"))

    def before_model(
        self, state: AgentExecState, runtime: Any
    ) -> dict[str, Any] | None:
        it = int(state.get("_it") or 0) + 1
        return {"_it": it}

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        if int((request.state or {}).get("_it") or 0) > self.max_iters:
            return AIMessage(
                content=_MAX_ITERATIONS_PROMPT,
                response_metadata={MAX_ITERATIONS_MARKER: True},
            )
        return handler(request)

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        """工具异常转 ToolMessage 回喂，不中断循环（对齐旧 ReactLoop 行为）；
        成功结果做体积钳制，防止大块检索内容长期驻留上下文。"""
        try:
            return self._clamp_tool_message(handler(request))
        except Exception as e:  # noqa: BLE001 - 回喂错误信息，不吞其他环节
            return ToolMessage(
                content=f"Error: {e}",
                tool_call_id=request.tool_call["id"],
                name=request.tool_call.get("name"),
            )

    def _clamp_tool_message(self, msg: Any) -> Any:
        if not isinstance(msg, ToolMessage) or not isinstance(msg.content, str):
            return msg
        limit = self.tool_result_max_chars
        text = msg.content
        if len(text) <= limit:
            return msg
        head_keep = max(limit - 200, 0)
        head = text[:head_keep]
        tail = text[-200:] if len(text) > limit else ""
        notice = f"\n\n[工具结果过长已截断：原始 {len(text)} 字符]"
        return ToolMessage(
            content=head + tail + notice,
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        )


class HitlMiddleware(AgentMiddleware):
    """HITL 拦截（T3.5 §16.4 MVP）：requires_hitl 工具不执行，改为回喂 ToolMessage。

    wrap_tool_call 最先短路命中：对 ``requires_hitl`` 集合内的工具调用**不执行**，
    回喂 ToolMessage（内容说明"需要用户确认，本轮未执行"），并在观测层记为
    status=awaiting_confirmation + hitl_status=pending。

    MVP 边界（见 brief §16.4 + report）：本任务只做 block-and-record，不做交互式
    approve/reject 恢复执行。恢复需流中暂停协议（LangGraph interrupt 接入聊天流），
    属后续阶段；此处只保证有副作用工具未经授权绝不执行。
    """

    def __init__(self, requires_hitl: set[str] | None = None) -> None:
        super().__init__()
        self.requires_hitl = set(requires_hitl or [])
        # 供 run_agent 落库：被拦截的工具调用明细（status=awaiting_confirmation）。
        self.blocked_tool_calls: list[dict] = []

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        tc = getattr(request, "tool_call", {}) or {}
        name = tc.get("name", "") if isinstance(tc, dict) else ""
        if name in self.requires_hitl:
            self.blocked_tool_calls.append({
                "name": name,
                "args": (tc.get("args", {}) if isinstance(tc, dict) else {}),
            })
            return ToolMessage(
                content=f"工具 {name} 需要用户确认，本轮未执行（HITL）",
                tool_call_id=request.tool_call["id"],
                name=name,
            )
        return handler(request)


class UsageAccumulatorMiddleware(AgentMiddleware):
    """累计 LLM token 用量（T1.4）。

    wrap_model_call 里 handler 返回 ModelResponse（result[0] 为 AIMessage）或直接
    AIMessage；从 ``usage_metadata`` 读 input_tokens/output_tokens 累加。缺失键静默
    降级（不阻塞对话），模型不吐 usage 时累计值保持 0。
    """

    def __init__(self) -> None:
        super().__init__()
        self.input_tokens = 0
        self.output_tokens = 0
        self._seen = False

    @staticmethod
    def _usage_of(msg: BaseMessage) -> dict | None:
        usage = getattr(msg, "usage_metadata", None)
        return usage if isinstance(usage, dict) else None

    def _add_usage(self, usage: dict | None) -> None:
        if not usage:
            return
        self._seen = True
        try:
            self.input_tokens += int(usage.get("input_tokens") or 0)
            self.output_tokens += int(usage.get("output_tokens") or 0)
        except (TypeError, ValueError):
            return  # 异常 usage 值静默忽略，不阻塞

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        response = handler(request)
        # ModelResponse(result=[...]) 或直接 AIMessage（短路中间件返回形态）
        msgs = getattr(response, "result", None)
        if msgs is None:
            msgs = [response]
        for m in msgs or []:
            if isinstance(m, AIMessage):
                self._add_usage(self._usage_of(m))
        return response

    def snapshot(self) -> tuple[int | None, int | None]:
        """返回 (input_tokens, output_tokens) 累计快照，供 run_agent 落 AgentResult。

        从未观测到 usage 时返回 (None, None)；观测到但累计为 0 时返回 (0, 0)。
        """
        if not self._seen:
            return None, None
        return self.input_tokens, self.output_tokens


class ObservabilityMiddleware(AgentMiddleware):
    """工具调用计时与错误记录（T1.4）。

    wrap_tool_call 记 started/finished 毫秒、name/args，异常记录 error 文本后原样
    上抛（工具错误仍由 MaxIterationsMiddleware 负责回喂 ToolMessage；此处只观测）。
    """

    def __init__(self) -> None:
        super().__init__()
        self.tool_call_details: list[dict] = []

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        tc = getattr(request, "tool_call", {}) or {}
        name = tc.get("name", "") if isinstance(tc, dict) else ""
        args = tc.get("args", {}) if isinstance(tc, dict) else {}
        started = time.perf_counter()
        error: str | None = None
        try:
            return handler(request)
        except Exception as e:  # noqa: BLE001 - 观测层不吞异常，记录后上抛
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            self.tool_call_details.append({
                "name": name,
                "args": args,
                "duration_ms": duration_ms,
                "error": error,
            })


class ContextCompactionMiddleware(AgentMiddleware):
    """上下文自动压缩：before_model 时 token 超阈值，把旧消息 LLM 总结后替换。

    策略（对齐 careercrew_core.memory.compaction.Compactor）：
    - 保留区：最近 retention_tokens 原封不动；
    - 压缩区：更早的消息分块总结 -> 合并成一条 SystemMessage 摘要；
    - 失败静默降级（LLM 异常时保留原文，不阻塞对话）。
    """

    def __init__(
        self,
        llm,
        token_threshold_ratio: float = 0.7,
        retention_tokens: int = 20000,
        max_summary_chunk_tokens: int = 4000,
        max_summary_chunks: int = 6,
        compaction_grace_calls: int = 3,
    ) -> None:
        super().__init__()
        self._llm = llm
        self._token_threshold_ratio = token_threshold_ratio
        self._retention_tokens = retention_tokens
        self._max_summary_chunk_tokens = max_summary_chunk_tokens
        self._max_summary_chunks = max_summary_chunks
        self._compaction_grace_calls = compaction_grace_calls
        # before_model 在 agent 循环的每次模型调用前都会执行；记录"上一次真正压缩
        # 发生在第几次调用"，压缩后给几轮宽限，避免长对话每轮重新过线、反复压缩。
        self._call_count = 0
        self._last_compaction_call = -compaction_grace_calls - 1

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        self._call_count += 1
        messages = list(state.get("messages") or [])
        if not messages:
            return None
        limit = int(self._retention_tokens / self._token_threshold_ratio)
        total = sum(_estimate_msg_tokens(m) for m in messages)
        if total < limit * self._token_threshold_ratio:
            return None
        # 刚压缩过：宽限期内即使再次过线也不再压缩（等上下文再积累几轮），
        # 否则 ReAct 循环每轮新增一条消息都会重新触发压缩，白耗多次 LLM 摘要。
        if self._call_count - self._last_compaction_call <= self._compaction_grace_calls:
            return None
        try:
            compacted = self._compact(messages)
            if compacted != messages:
                self._last_compaction_call = self._call_count
                return {"messages": compacted}
        except Exception:
            return None  # 压缩失败不阻塞
        return None

    def _compact(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        kept: list[BaseMessage] = []
        total = 0
        for m in reversed(messages):
            t = _estimate_msg_tokens(m)
            if total + t <= self._retention_tokens:
                kept.append(m)
                total += t
            else:
                break
        kept = list(reversed(kept))
        compressibles = messages[: len(messages) - len(kept)]
        if not compressibles:
            return messages
        summary = self._summarize(compressibles)
        if not summary:
            return messages
        return [SystemMessage(content=f"[历史压缩摘要]\n{summary}")] + kept

    def _summarize(self, messages: list[BaseMessage]) -> str:
        chunks: list[list[BaseMessage]] = []
        cur: list[BaseMessage] = []
        total = 0
        for m in messages:
            t = _estimate_msg_tokens(m)
            if total + t > self._max_summary_chunk_tokens and cur:
                chunks.append(cur)
                cur, total = [m], t
            else:
                cur.append(m)
                total += t
        if cur:
            chunks.append(cur)
        parts: list[str] = []
        for c in chunks[: self._max_summary_chunks]:
            # 只保留有实际文本的消息：纯工具调用消息 content=""，进了摘要 prompt
            # 只会产出"AIMessage:"空行，浪费一次 LLM 调用并注入垃圾摘要
            lines = [
                f"{type(m).__name__}: {str(m.content).strip()[:500]}"
                for m in c
                if str(m.content).strip()
            ]
            if not lines:
                continue  # 该 chunk 全为空内容，直接跳过
            text = "\n".join(lines)
            try:
                resp = self._llm.invoke(f"把以下对话压缩成要点摘要（中文，不超过 200 字）：\n{text}")
                parts.append(resp.content if isinstance(resp.content, str) else str(resp.content))
            except Exception:
                return ""  # LLM 失败 -> 不压缩（保留原文，不阻塞）
        return "\n".join(f"- {p}" for p in parts if p)


_CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3000-\u303f\uff01-\uff5e]")


def _estimate_msg_tokens(msg: BaseMessage) -> int:
    """按内容估算 token 数（CJK 感知）。

    中文在主流分词器（DeepSeek/GPT/Qwen）下约 1 字 ≈ 0.6~1 token，英文约
    4 字符 ≈ 1 token。此前统一 len//4 会把中文内容低估 3~4 倍，导致
    ContextCompactionMiddleware 的阈值判定几乎永不触发——实测上下文膨胀到
    单次调用 6万~20万 真实 token 而压缩从未发生（LangSmith trace 佐证）。

    不能用 usage_metadata.input_tokens 估算单条消息：那是一条消息生成时
    **整个上下文**的 token 数（可达数万），会把小对话误判为超限。
    """
    text = str(msg.content)
    cjk = len(_CJK_CHAR_RE.findall(text))
    other = len(text) - cjk
    return cjk + other // 4 + 8


def build_agent(
    llm: BaseChatModel,
    tools: list[BaseTool] | None,
    system_prompt: str,
    max_iterations: int = 10,
    extra_middleware: list[AgentMiddleware] | None = None,
    hitl_requires: set[str] | None = None,
):
    """编译 create_agent 图（tools=None 时等效单模型节点）。

    观测中间件（UsageAccumulator / Observability）总是装配，并把实例挂在
    返回图的 ``_observability`` 属性上供 run_agent 读取（不污染 AgentResult 契约）。
    hitl_requires 非空时装配 HitlMiddleware（T3.5 HITL 拦截），实例挂 ``_hitl``。
    """
    usage_mw = UsageAccumulatorMiddleware()
    obs_mw = ObservabilityMiddleware()
    middleware: list[AgentMiddleware] = [
        MaxIterationsMiddleware(max_iterations),
        usage_mw,
        obs_mw,
    ]
    hitl_mw = HitlMiddleware(hitl_requires) if hitl_requires else None
    if hitl_mw is not None:
        # HITL 拦截须先于 Observability（先短路，Observability 记录被拦截的调用；
        # 顺序：Hitl -> Obs -> ...），放在 Obs 之前以便被拦截调用也被计时/记录。
        middleware.insert(len(middleware) - 1, hitl_mw)
    if extra_middleware:
        middleware.extend(extra_middleware)
    agent = create_agent(
        model=llm,
        tools=tools or None,
        system_prompt=system_prompt,
        state_schema=AgentExecState,
        middleware=middleware,
    )
    agent._observability = (usage_mw, obs_mw)  # type: ignore[attr-defined]
    agent._hitl = hitl_mw  # type: ignore[attr-defined]
    return agent


_SPECIAL_TOKEN_RE = re.compile(r"<\|(?:begin_of_box|end_of_box)\|>")
_FINALIZATION_TOOL_NAMES = {"memory_write", "profile_update"}

# 伪工具调用语法：模型在所需工具未绑定时（如意图级裁剪后的普通规划），
# 会模仿历史里的调用格式把 ``<call name="rag_query">`` 等当正文输出给用户，
# 且常就此截断。与 _SPECIAL_TOKEN_RE 同类：模型产物清理，不是业务内容。
_PSEUDO_TOOL_BLOCK_RE = re.compile(
    r"<(?:call|tool_call|function_call)\b[^>]*>"
    r".*?"
    r"</(?:call|tool_call|function_call)>",
    re.IGNORECASE | re.DOTALL,
)
_PSEUDO_TOOL_TAIL_RE = re.compile(
    r"<(?:call|tool_call|function_call)\b[^>]*>"
    r"(?:(?!<(?:call|tool_call|function_call)[\s>]).)*\Z",
    re.IGNORECASE | re.DOTALL,
)
_PSEUDO_ARG_TAG_RE = re.compile(r"</?arg\b[^>]*/?>", re.IGNORECASE)


def strip_pseudo_tool_calls(text: str) -> str:
    """剥离模型写成正文文本的伪工具调用语法。

    删除完整伪调用块、结尾被截断的未闭合块和游离 ``<arg>`` 标签，保留正常
    正文。真实工具调用走 ``AIMessage.tool_calls`` 结构化通道，不受影响。
    """
    if not text or "<" not in text:
        return text
    cleaned = _PSEUDO_TOOL_BLOCK_RE.sub("", text)
    cleaned = _PSEUDO_TOOL_TAIL_RE.sub("", cleaned)
    cleaned = _PSEUDO_ARG_TAG_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


class PseudoToolCallStreamFilter:
    """流式回调过滤：拦截伪工具调用块，避免其以正文形式流给用户。

    与 :func:`strip_pseudo_tool_calls` 语义一致，面向 token 级 chunk：
    - 遇到伪调用开标签进入抑制态，直到闭标签出现，整块丢弃；
    - 正常态只回吐安全前缀，扣留可能是开标签前缀的尾部碎片；
    - 抑制未结束时流终止（``flush``），残余内容一并丢弃。
    """

    _OPEN_RE = re.compile(r"<(?:call|tool_call|function_call)\b", re.IGNORECASE)
    _CLOSE_RE = re.compile(r"</(?:call|tool_call|function_call)\s*>", re.IGNORECASE)
    _OPEN_TAGS = ("<call", "<tool_call", "<function_call")
    _MAX_OPEN_TAG_LEN = max(len(tag) for tag in _OPEN_TAGS)

    def __init__(self, sink) -> None:
        self._sink = sink
        self._buf: list[str] = []
        self._suppressed = False

    def __call__(self, text: str) -> None:
        if not text:
            return
        self._buf.append(text)
        self._drain(final=False)

    def flush(self) -> None:
        """流结束时调用：放行安全残余；抑制中的伪调用块直接丢弃。"""
        self._drain(final=True)

    def _emit(self, piece: str) -> None:
        if piece:
            self._sink(piece)

    def _drain(self, *, final: bool) -> None:
        buf = "".join(self._buf)
        self._buf = []
        while True:
            if self._suppressed:
                m = self._CLOSE_RE.search(buf)
                if m is None:
                    break
                buf = buf[m.end():]
                self._suppressed = False
            else:
                m = self._OPEN_RE.search(buf)
                if m is None:
                    break
                self._emit(buf[: m.start()])
                buf = buf[m.end():]
                self._suppressed = True
        if self._suppressed:
            if final:
                # 截断的伪调用块：整体丢弃，不放行半截语法
                self._suppressed = False
            else:
                self._buf.append(buf)
            return
        if final:
            self._emit(buf)
            return
        hold = self._partial_hold_len(buf)
        if hold:
            self._buf.append(buf[-hold:])
            buf = buf[:-hold]
        self._emit(buf)

    def _partial_hold_len(self, buf: str) -> int:
        low = buf.lower()
        n = len(low)
        for start in range(max(0, n - (self._MAX_OPEN_TAG_LEN - 1)), n):
            frag = low[start:]
            if any(tag.startswith(frag) for tag in self._OPEN_TAGS):
                return n - start
        return 0


def _msg_text(msg: BaseMessage) -> str:
    """提取消息文本;剥离视觉定位类模型的特殊标记(如 GLM-4.5V 的 box token)。"""
    text = msg.content if isinstance(msg.content, str) else ""
    return _SPECIAL_TOKEN_RE.sub("", text)


def _recover_hidden_final_text(iterations: list[ReactIteration]) -> str:
    """恢复与收尾工具同轮生成、但被展示过滤隐藏的最终正文。

    ``include_tool_call_text=False`` 用于屏蔽“我来搜索”等过程话术，但部分模型会
    把完整报告和 ``memory_write``/``profile_update`` 放在同一条 AIMessage 中，
    随后再返回一个空消息结束。这种情况下若一概丢弃带工具调用的文本，用户只能
    看到空结果兜底。这里只恢复纯收尾工具轮，仍不展示 search/rag 等过程轮文本。
    """
    for iteration in reversed(iterations):
        text = (iteration.content or "").strip()
        if not text or not iteration.tool_calls:
            continue
        names = {
            str(call.get("name") or "")
            for call in iteration.tool_calls
            if isinstance(call, dict)
        }
        if names and names <= _FINALIZATION_TOOL_NAMES:
            return text
    return ""


def run_agent(
    agent: Any,
    messages: list[BaseMessage],
    stream_callback=None,
    max_iterations: int = 10,
    include_tool_call_text: bool = True,
) -> AgentResult:
    """驱动图并聚合 AgentResult。

    stream_mode=["messages","updates"]：
    - "messages"：token 级事件，``metadata["langgraph_node"]=="model"`` 的文本 chunk
      喂 ``stream_callback``（tools 节点事件不转发）；合成的停止消息不转发。
    - "updates"：``{"model": {"messages": [...]}}`` 记一轮迭代，
      ``{"tools": {"messages": [...]}}`` 累计 ToolMessage 数（= 工具调用数）。
    """
    iterations: list[ReactIteration] = []
    tool_calls_total = 0
    last_iter_idx = -1
    max_reached = False
    stop_content = ""
    pending_model_chunks: list[str] = []
    if stream_callback is not None:
        stream_callback = PseudoToolCallStreamFilter(stream_callback)

    try:
        stream = agent.stream(
            {"messages": list(messages)},
            stream_mode=["messages", "updates"],
            # langchain 1.3 起 before_model 是独立图节点，每轮迭代实际消耗
            # 3 个 super-step（before_model + model + tools）；旧公式 2*N+6
            # 会在 MaxIterationsMiddleware 的 marker（约 3*N+2 处）触发前
            # 先撞 recursion_limit（实测 GraphRecursionError → 空 content）。
            # 3*N+10 保证中间件短路先于递归上限。
            config={"recursion_limit": max_iterations * 3 + 10},
        )
        for event in stream:
            mode, payload = event
            if mode == "messages":
                msg, meta = payload
                if meta.get("langgraph_node") == "model" and isinstance(msg, AIMessage):
                    if msg.response_metadata.get(MAX_ITERATIONS_MARKER):
                        max_reached = True
                        continue
                    text = _msg_text(msg)
                    if text and stream_callback and include_tool_call_text:
                        stream_callback(text)
                    elif text and stream_callback:
                        pending_model_chunks.append(text)
            else:
                # updates：model 节点 -> 一轮迭代；tools 节点 -> 工具调用数
                if "model" in payload:
                    model_msgs = (payload.get("model") or {}).get("messages") or []
                    for m in model_msgs:
                        if not isinstance(m, AIMessage):
                            continue
                        if m.response_metadata.get(MAX_ITERATIONS_MARKER):
                            max_reached = True
                            stop_content = _msg_text(m) or _MAX_ITERATIONS_PROMPT
                            continue
                        iterations.append(
                            ReactIteration(
                                iteration=len(iterations),
                                content=strip_pseudo_tool_calls(_msg_text(m)),
                                tool_calls=list(m.tool_calls or []),
                            )
                        )
                        last_iter_idx = len(iterations) - 1
                        if not include_tool_call_text and stream_callback:
                            if not m.tool_calls and pending_model_chunks:
                                stream_callback("".join(pending_model_chunks))
                            pending_model_chunks.clear()
                if "tools" in payload:
                    tool_msgs = (payload.get("tools") or {}).get("messages") or []
                    for m in tool_msgs:
                        if isinstance(m, ToolMessage):
                            tool_calls_total += 1
                            if last_iter_idx >= 0:
                                iterations[last_iter_idx].tool_results.append(m.content)
    except Exception as e:  # noqa: BLE001 - 记录后上抛，由 API 生命周期标记 failed
        logger.exception("agent.stream 执行异常，交由上层标记失败：%s", e)
        raise
    if isinstance(stream_callback, PseudoToolCallStreamFilter):
        # 只在成功路径 flush：放行扣留的安全尾部；异常路径保持原失败语义
        stream_callback.flush()

    if max_reached:
        content = stop_content or _MAX_ITERATIONS_PROMPT
    else:
        # 多轮 ReAct 的最终可见内容 = 全部非空模型文本按序拼接（与流式回调
        # 所见一致）。常见形态：报告正文 -> memory_write/profile_update 收尾
        # 工具 -> 一句收尾语；若只取 iterations[-1] 会把正文丢得只剩一句。
        texts = [
            it.content.strip()
            for it in iterations
            if it.content
            and it.content.strip()
            and (include_tool_call_text or not it.tool_calls)
        ]
        content = "\n\n".join(texts)
        if not content and not include_tool_call_text:
            content = _recover_hidden_final_text(iterations)
            # 工具轮文本此前没有进入 callback；恢复后补发一次，让流式前端与最终
            # 持久化内容保持一致。
            if content and stream_callback:
                stream_callback(content)
    if max_reached:
        stopped_reason = "max_iterations"
    else:
        stopped_reason = "final_answer"

    # T1.4 观测字段：从 build_agent 挂载的观测中间件读取累计值
    usage_mw, obs_mw = getattr(agent, "_observability", (None, None))
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_call_details: list[dict] = []
    blocked_tool_calls: list[dict] = []
    if usage_mw is not None:
        in_tok, out_tok = usage_mw.snapshot()
        input_tokens = in_tok
        output_tokens = out_tok
    if obs_mw is not None:
        tool_call_details = list(obs_mw.tool_call_details)
    hitl_mw = getattr(agent, "_hitl", None)
    if hitl_mw is not None:
        blocked_tool_calls = list(hitl_mw.blocked_tool_calls)

    return AgentResult(
        content=content,
        iterations=iterations,
        tool_calls_total=tool_calls_total,
        stopped_reason=stopped_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_call_details=tool_call_details,
        blocked_tool_calls=blocked_tool_calls,
    )
