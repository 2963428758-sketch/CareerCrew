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
from dataclasses import dataclass, field
from typing import Annotated, Any, NotRequired, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, ToolMessage
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
    """ReAct 循环产出（契约不变）。"""

    content: str
    iterations: list[ReactIteration]
    tool_calls_total: int
    stopped_reason: str  # final_answer | max_iterations | error


class MaxIterationsMiddleware(AgentMiddleware):
    """迭代上限：before_model 递增 _it，wrap_model_call 超限短路。"""

    def __init__(self, max_iters: int) -> None:
        super().__init__()
        self.max_iters = max_iters

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
        """工具异常转 ToolMessage 回喂，不中断循环（对齐旧 ReactLoop 行为）。"""
        try:
            return handler(request)
        except Exception as e:  # noqa: BLE001 - 回喂错误信息，不吞其他环节
            return ToolMessage(
                content=f"Error: {e}",
                tool_call_id=request.tool_call["id"],
                name=request.tool_call.get("name"),
            )


def build_agent(
    llm: BaseChatModel,
    tools: list[BaseTool] | None,
    system_prompt: str,
    max_iterations: int = 10,
):
    """编译 create_agent 图（tools=None 时等效单模型节点）。"""
    return create_agent(
        model=llm,
        tools=tools or None,
        system_prompt=system_prompt,
        state_schema=AgentExecState,
        middleware=[MaxIterationsMiddleware(max_iterations)],
    )


def _msg_text(msg: BaseMessage) -> str:
    return msg.content if isinstance(msg.content, str) else ""


def run_agent(
    agent: Any,
    messages: list[BaseMessage],
    stream_callback=None,
    max_iterations: int = 10,
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
    failed = False
    stop_content = ""

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
                    if text and stream_callback:
                        stream_callback(text)
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
                                content=_msg_text(m),
                                tool_calls=list(m.tool_calls or []),
                            )
                        )
                        last_iter_idx = len(iterations) - 1
                if "tools" in payload:
                    tool_msgs = (payload.get("tools") or {}).get("messages") or []
                    for m in tool_msgs:
                        if isinstance(m, ToolMessage):
                            tool_calls_total += 1
                            if last_iter_idx >= 0:
                                iterations[last_iter_idx].tool_results.append(m.content)
    except Exception as e:  # noqa: BLE001 - 任何执行异常标记 error，不吞给上层
        failed = True
        logger.exception("agent.stream 执行异常（run_agent 标记 stopped_reason=error）：%s", e)

    if max_reached:
        content = stop_content or _MAX_ITERATIONS_PROMPT
    else:
        content = iterations[-1].content if iterations else ""
    if failed:
        stopped_reason = "error"
    elif max_reached:
        stopped_reason = "max_iterations"
    else:
        stopped_reason = "final_answer"
    return AgentResult(
        content=content,
        iterations=iterations,
        tool_calls_total=tool_calls_total,
        stopped_reason=stopped_reason,
    )
