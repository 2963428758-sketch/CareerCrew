"""手写 ReAct 循环内核（B2）。

可见循环：组装上下文 -> 调 LLM(带工具) -> 判 tool_call -> 执行 -> 回喂 -> 再循环。
不依赖 create_react_agent 黑盒，工具推理过程全链路 trace 可回放（L3 Dashboard 用）。

每轮记录 ReactIteration（thought=content / tool_calls / tool_results）到 trace。
结束条件：LLM 无 tool_call（final_answer）/ 超过 max_iterations。
工具执行失败不崩循环，错误回喂给 LLM（对齐 DEV_SPEC 5.7 降级策略）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import BaseTool

from careercrew_ai.react.context_builder import ContextBuilder


@dataclass
class ReactIteration:
    """单轮 ReAct 迭代记录（trace 用）。"""

    iteration: int
    content: str  # LLM 文本输出（thought）
    tool_calls: list[dict] = field(default_factory=list)  # 本轮 tool_calls（空=最终答案）
    tool_results: list[Any] = field(default_factory=list)  # 本轮工具执行结果


@dataclass
class AgentResult:
    """ReAct 循环产出。"""

    content: str  # 最终答案
    iterations: list[ReactIteration]  # 每轮 trace
    tool_calls_total: int  # 总工具调用数
    stopped_reason: str  # final_answer | max_iterations | error


class ReactLoop:
    """手写 ReAct 循环（可见 while）。"""

    def __init__(
        self,
        max_iterations: int = 10,
        context_builder: ContextBuilder | None = None,
        tracer=None,
        stream_callback=None,
    ) -> None:
        self.max_iterations = max_iterations
        self._context_builder = context_builder or ContextBuilder()
        self._tracer = tracer  # 可选 TraceRecorder（L3）
        self._stream_callback = stream_callback  # 可选：逐 token 流式输出回调(text)->None

    def run(
        self,
        system_prompt: str,
        messages: list[BaseMessage],
        tools: list[BaseTool],
        llm: BaseChatModel,
    ) -> AgentResult:
        convo = self._context_builder.build(system_prompt, messages)
        bound_llm = llm.bind_tools(tools) if tools else llm
        tool_map = {t.name: t for t in tools}
        iterations: list[ReactIteration] = []
        tool_calls_total = 0
        content = ""

        for i in range(self.max_iterations):
            content, tool_calls, resp = self._invoke(bound_llm, convo)
            it = ReactIteration(iteration=i, content=content, tool_calls=tool_calls)
            iterations.append(it)
            if self._tracer:
                self._tracer.agent_loop(
                    agent="react", iteration=i, content=content,
                    tool_calls=[tc.get("name") for tc in tool_calls],
                    tool_calls_total=tool_calls_total,
                )

            # 无 tool_call -> 最终答案
            if not tool_calls:
                return AgentResult(
                    content=content,
                    iterations=iterations,
                    tool_calls_total=tool_calls_total,
                    stopped_reason="final_answer",
                )

            # 有 tool_call：AIMessage 回喂 + 执行工具 + ToolMessage 回喂
            convo.append(resp)
            for tc in tool_calls:
                result = self._execute_tool(tool_map, tc)
                it.tool_results.append(result)
                convo.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
                tool_calls_total += 1

        # 超轮次
        return AgentResult(
            content=content,
            iterations=iterations,
            tool_calls_total=tool_calls_total,
            stopped_reason="max_iterations",
        )

    def _invoke(self, bound_llm, convo):
        """调 LLM。有 stream_callback 则流式(逐 token 回调, 用户不等)；否则一次 invoke。

        Returns: (content, tool_calls, resp)  resp 为完整 AIMessage(带 tool_calls 用于回喂)。
        """
        if self._stream_callback is None:
            resp = bound_llm.invoke(convo)
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            return content, list(resp.tool_calls or []), resp

        # 流式：accumulate chunks（内容 + tool_call_chunks），逐 token 回调
        from langchain_core.messages import AIMessage

        msg = None
        for chunk in bound_llm.stream(convo):
            msg = chunk if msg is None else msg + chunk
            if chunk.content:
                self._stream_callback(chunk.content)
        if msg is None:
            msg = AIMessage(content="")
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        return content, list(getattr(msg, "tool_calls", None) or []), msg

    @staticmethod
    def _execute_tool(tool_map: dict[str, BaseTool], tool_call: dict) -> Any:
        name = tool_call["name"]
        args = tool_call.get("args", {})
        tool = tool_map.get(name)
        if tool is None:
            return f"[error] 未知工具: {name}"
        try:
            return tool.invoke(args)
        except Exception as e:  # 工具执行失败不崩循环，错误回喂给 LLM
            return f"[error] {type(e).__name__}: {e}"
