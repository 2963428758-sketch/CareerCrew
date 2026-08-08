"""agent 节点基类（B4）。

套手写 ReAct 循环：读 system prompt + state.messages -> ReactLoop.run -> 产出写回 state。
- messages：最终答案作为 AIMessage 追加（add_messages reducer）。
- agent_outputs：本 agent 产出存到 agent_outputs[name]（merge_dicts reducer 聚合多 agent）。

作为 LangGraph 节点 callable：run(state) -> state_update。
"""
from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from careercrew_ai.react.react_loop import AgentResult, ReactLoop
from careercrew_core.state.thread_state import CareerCrewState
from careercrew_core.tools.registry import ToolRegistry


class BaseAgent:
    """agent 节点基类（LangGraph 节点 callable）。"""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        llm: BaseChatModel,
        tools: list[BaseTool] | ToolRegistry | None = None,
        max_iterations: int = 10,
        tracer=None,  # 可选 TraceRecorder（L3 全链路打点）
        stream_callback=None,  # 可选: 流式输出回调(text)->None, 用户不等
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.llm = llm
        self.tools = tools or []
        self.loop = ReactLoop(
            max_iterations=max_iterations, tracer=tracer, stream_callback=stream_callback
        )
        self.last_result: AgentResult | None = None  # 供 trace/调试取完整迭代记录

    def run(self, state: CareerCrewState) -> dict:
        """LangGraph 节点入口：套 ReAct 循环，返回 state 更新。"""
        messages = list(state.get("messages", []))
        result = self.loop.run(self.system_prompt, messages, self._bindable_tools(), self.llm)
        self.last_result = result
        return self._build_update(result)

    def _bindable_tools(self) -> list[BaseTool]:
        if isinstance(self.tools, ToolRegistry):
            return self.tools.bindable_tools()
        return list(self.tools)

    def _build_update(self, result: AgentResult) -> dict:
        return {
            "messages": [AIMessage(content=result.content, name=self.name)],
            "agent_outputs": {
                self.name: {
                    "content": result.content,
                    "stopped_reason": result.stopped_reason,
                    "tool_calls_total": result.tool_calls_total,
                    "iterations": len(result.iterations),
                }
            },
        }
