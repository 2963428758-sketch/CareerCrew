"""统一工具注册表（B5）。

MCP 工具与内部函数同一接口：ToolSpec 包 langchain BaseTool + CareerCrew 元数据
（source / requires_confirmation / parallel_safe）。agent 经 ReAct 循环统一调用；
requires_confirmation=True 的工具触发 HITL（K 阶段接 LangGraph interrupt）。

设计：
- 复用 langchain BaseTool（@tool / StructuredTool）的 args_schema 与 bind_tools 兼容性，
  不重新发明 JSON schema 解析。
- ToolSpec 叠加 CareerCrew 元数据（source / requires_confirmation / parallel_safe）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool


@dataclass
class ToolSpec:
    """工具规格：langchain BaseTool + CareerCrew 元数据。"""

    tool: BaseTool
    source: str = "internal"  # internal | mcp
    requires_confirmation: bool = False
    parallel_safe: bool = True

    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def description(self) -> str:
        return self.tool.description or ""


class ToolRegistry:
    """统一工具注册表。"""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """注册工具（同名覆盖）。"""
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._specs:
            raise KeyError(f"工具未注册: {name}")
        return self._specs[name]

    def has(self, name: str) -> bool:
        return name in self._specs

    def list_names(self) -> list[str]:
        return list(self._specs)

    def list_specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def bindable_tools(self) -> list[BaseTool]:
        """返回 BaseTool 列表，供 llm.bind_tools() 用。"""
        return [spec.tool for spec in self._specs.values()]

    def high_risk_names(self) -> list[str]:
        """requires_confirmation=True 的工具名（HITL 闸门用，K 阶段）。"""
        return [n for n, s in self._specs.items() if s.requires_confirmation]

    def execute(self, name: str, **kwargs: Any) -> Any:
        """执行工具（调 BaseTool.invoke）。高风险工具的 HITL 拦截在 supervisor 层做。"""
        return self.get(name).tool.invoke(kwargs)
