"""agent 节点基类（B4，AGENT_LANGSMITH_SPEC Part A 改造）。

内部驱动 LangChain 1.x ``create_agent`` 编译图（LLM/工具/循环/流式事件由平台提供），
对外契约不变：
- ``run(state) -> state_update``（LangGraph 节点 callable）
- ``last_result: AgentResult``（content / stopped_reason / tool_calls_total / iterations）
- ``agent_outputs[name]`` 聚合多 agent 产出

``run`` 挂 LangSmith 根 run（``agent.<name>``），metadata 带 user_id/thread_id/stage；
逐轮明细过程交给 LangSmith，本地只保留轻量迭代记录。
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from careercrew_ai.agents.langchain_agent import AgentResult, build_agent, run_agent
from careercrew_core.state.thread_state import CareerCrewState
from careercrew_core.tools.registry import ToolRegistry
from careercrew_core.tracing.langsmith import attach_run_metadata, traced_call


class BaseAgent:
    """agent 节点基类（LangGraph 节点 callable）。"""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        llm: BaseChatModel,
        tools: list[BaseTool] | ToolRegistry | None = None,
        max_iterations: int = 10,
        stream_callback=None,  # 可选: 流式输出回调(text)->None, 用户不等
        memory_injector=None,  # 可选: Callable[[str, str], str | None]（user_id, query）-> preamble
        history_loader=None,   # 可选: Callable[[str, str], list]（user_id, thread_id）-> 历史消息
        compaction=None,       # 可选: dict(token_threshold_ratio/retention_tokens/max_summary_chunk_tokens)
        hitl_requires: set[str] | None = None,  # T3.5：本轮需 HITL 确认的工具名集合
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.llm = llm
        self.tools = tools or []
        self.max_iterations = max_iterations
        self.stream_callback = stream_callback
        self.memory_injector = memory_injector
        self.history_loader = history_loader
        extra_middleware = []
        if compaction is not None:
            from careercrew_ai.agents.langchain_agent import ContextCompactionMiddleware

            extra_middleware.append(ContextCompactionMiddleware(llm, **compaction))
        self.agent = build_agent(
            llm=llm,
            tools=self._bindable_tools() or None,
            system_prompt=system_prompt,
            max_iterations=max_iterations,
            extra_middleware=extra_middleware or None,
            hitl_requires=hitl_requires or None,
        )
        self.last_result: AgentResult | None = None  # 供 trace/调试取完整迭代记录

    def run(self, state: CareerCrewState) -> dict:
        """LangGraph 节点入口：驱动 create_agent 图（LangSmith 根 run），返回 state 更新。"""
        return traced_call(
            self._run_impl,
            name=f"agent.{self.name}",
            run_type="chain",
            state=state,
        )

    def _run_impl(self, state: CareerCrewState) -> dict:
        attach_run_metadata(
            user_id=state.get("user_id", ""),
            thread_id=state.get("thread_id", ""),
            stage=state.get("stage", ""),
        )
        messages = list(state.get("messages", []))
        if self.history_loader is not None:
            try:
                history = self.history_loader(
                    state.get("user_id", ""), state.get("thread_id", ""),
                    state.get("pending_user_entry_id"),
                )
                if history:
                    messages = history + messages
            except Exception:
                pass  # 历史恢复失败不阻塞
        if self.memory_injector is not None:
            query = ""
            for m in reversed(messages):
                if getattr(m, "type", "") == "human" or m.__class__.__name__ == "HumanMessage":
                    query = str(m.content or "")
                    break
            try:
                preamble = self.memory_injector(state.get("user_id", ""), query)
            except Exception:
                preamble = None
            if preamble:
                from langchain_core.messages import SystemMessage

                messages = [SystemMessage(content=preamble)] + messages
        result = run_agent(
            self.agent, messages, self.stream_callback, self.max_iterations
        )
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
