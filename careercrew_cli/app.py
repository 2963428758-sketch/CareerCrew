"""CareerCrew CLI 入口。A3 起接入 load_settings 启动校验（config 子命令 fail-fast）。"""
from __future__ import annotations

import argparse
import sys

__version__ = "0.1.0"

BANNER = (
    "CareerCrew v{v} - 多智能体职业顾问团队\n"
    "职位匹配 / 简历 / 面试 / 谈薪 / 规划"
).format(v=__version__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="careercrew",
        description="CareerCrew 求职顾问 CLI",
    )
    parser.add_argument("--version", action="version", version=f"careercrew {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("chat", help="启动求职顾问对话（占位，G 阶段落地）")
    sub.add_parser("config", help="加载并校验配置（fail-fast）")
    return parser


def _run_config_check() -> int:
    """加载配置并打印摘要；失败 fail-fast 返回 1。"""
    from careercrew_core.state.settings import load_settings

    try:
        settings = load_settings()
    except Exception as e:  # SettingsError 等，统一可读输出
        print(f"[配置校验失败] {e}", file=sys.stderr)
        return 1
    print("[配置校验通过]")
    print(f"  LLM        : {settings.llm.model} @ {settings.llm.base_url}")
    print(f"  Embedding  : {settings.embedding.provider} ({settings.embedding.model})")
    print(f"  Rerank     : {settings.rerank.backend}")
    print(f"  VectorStore: {settings.vector_store.backend}")
    print(f"  RAG        : {settings.rag.retrieval.mode} / contextual={settings.rag.chunking.contextual}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "config":
        return _run_config_check()
    print(BANNER)
    if args.command is None or args.command == "chat":
        print("\n[占位] 求职周期工作流将在 G 阶段（CLI + M1 闭环）落地。")
        print("当前可用：careercrew --version | careercrew config")
    return 0


if __name__ == "__main__":
    sys.exit(main())
