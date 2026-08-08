"""CLI 渲染层（G1）。

对话渲染 + agent 输出 + HITL 提示。ANSI 着色，纯文本 fallback 无。
"""
from __future__ import annotations

_RESET = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_RED = "\033[31m"


class Renderer:
    """CLI 对话渲染 + HITL 提示。"""

    def banner(self) -> None:
        print(_CYAN + "CareerCrew 求职顾问 — 多智能体职业顾问团队" + _RESET)

    def show_user(self, text: str) -> None:
        print(f"\n{_BOLD}你{_RESET}: {text}")

    def show_agent(self, agent_name: str, text: str) -> None:
        print(f"\n{_GREEN}[{agent_name}]{_RESET}")
        print(text)

    def show_status(self, text: str) -> None:
        print(f"  {_YELLOW}{text}{_RESET}")

    def show_tool(self, name: str, args: dict) -> None:
        print(f"  {_YELLOW}→ 调工具: {name}({args}){_RESET}")

    def show_error(self, text: str) -> None:
        print(f"{_RED}✗ {text}{_RESET}")

    def stream(self, text: str) -> None:
        """流式输出 token（不换行, 实时刷新, 用户不等）。"""
        print(text, end="", flush=True)

    def stream_end(self) -> None:
        """流式结束换行。"""
        print()

    def prompt_choice(self, prompt: str) -> str:
        return input(prompt)
