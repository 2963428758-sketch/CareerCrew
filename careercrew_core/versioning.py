"""版本标识（§8.1 / T1.5）：prompt sha256 版本 + agent git-sha 版本。

- ``prompt_version(text)``：UTF-8 编码后 sha256，返回 ``sha256:<64 hex 小写>``；
  空文本 / None -> ``"unversioned"``（质量后台对 unversioned 显示告警，绝不返回 unknown）。
- ``agent_version()``：模块级缓存；优先环境变量 ``CAREERCREW_AGENT_VERSION``
  （strip 后非空才用），否则 ``git rev-parse HEAD``（cwd=仓库根，超时 2s）；
  任何失败 -> ``"unversioned"``。
- ``prompt_version_for_agent(agent_id)``：惰性 registry，agent_id -> prompt sha256。
  命中 6 个 agent 各自 ``prompt_source()``（与 __init__ 读取逻辑完全一致），
  另注册 ``interviewer_chat``（interview 路由的聊天 prompt）；
  registry 未命中 -> ``"unversioned"``。

registry 惰性（按需 import 各 agent 模块 / interview 路由），避免模块加载时拖入
langchain 等重依赖。
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

# 项目根：careercrew_core/versioning.py -> parents[1] = 项目根
_PROJECT_ROOT = Path(__file__).resolve().parents[1]

_UNVERSIONED = "unversioned"

_cached_agent_version: str | None = None

# 6 个业务 agent 的 agent_id；interviewer_chat 是 interview 路由聊天 prompt 的独立键。
# 惰性 import（见 prompt_version_for_agent），避免模块加载期拖入 langchain 等重依赖。
_REGISTRY_AGENTS = (
    "job_matcher",
    "resume_advisor",
    "career_planner",
    "knowledge_advisor",
    "interviewer",
    "salary_negotiator",
)


def prompt_version(text: str | None) -> str:
    """计算 prompt 文本的 sha256 版本串；空/None -> unversioned。"""
    if not text or not text.strip():
        return _UNVERSIONED
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def agent_version() -> str:
    """返回 agent 版本（git sha 或环境变量注入），模块级缓存，绝不返回 unknown。"""
    global _cached_agent_version
    if _cached_agent_version is not None:
        return _cached_agent_version

    env = os.environ.get("CAREERCREW_AGENT_VERSION", "").strip()
    if env:
        _cached_agent_version = env
        return _cached_agent_version

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=2,
        )
        sha = proc.stdout.strip()
        if proc.returncode == 0 and sha:
            _cached_agent_version = sha
            return _cached_agent_version
    except Exception:  # noqa: BLE001 - 版本获取失败不阻断主链路
        pass

    _cached_agent_version = _UNVERSIONED
    return _cached_agent_version


def prompt_version_for_agent(agent_id: str | None) -> str:
    """按 agent_id 惰性计算 prompt sha256 版本；未命中 -> unversioned。"""
    if not agent_id:
        return _UNVERSIONED

    if agent_id == "interviewer_chat":
        from careercrew_api.routers.interview import _CHAT_PROMPT_PATH

        return _prompt_file_version(_CHAT_PROMPT_PATH)

    if agent_id in _REGISTRY_AGENTS:
        module = _import_agent_module(agent_id)
        if module is None:
            return _UNVERSIONED
        return prompt_version(module.prompt_source())

    return _UNVERSIONED


def _import_agent_module(agent_id: str):
    """惰性 import 对应 agent 模块（返回 module 或 None）。"""
    try:
        if agent_id == "job_matcher":
            from careercrew_core.agents import job_matcher
            return job_matcher
        if agent_id == "resume_advisor":
            from careercrew_core.agents import resume_advisor
            return resume_advisor
        if agent_id == "career_planner":
            from careercrew_core.agents import career_planner
            return career_planner
        if agent_id == "knowledge_advisor":
            from careercrew_core.agents import knowledge_advisor
            return knowledge_advisor
        if agent_id == "interviewer":
            from careercrew_core.agents import interviewer
            return interviewer
        if agent_id == "salary_negotiator":
            from careercrew_core.agents import salary_negotiator
            return salary_negotiator
    except Exception:  # noqa: BLE001 - 版本计算失败降级 unversioned
        return None
    return None


def _prompt_file_version(path: Path) -> str:
    """读 prompt 文件文本并返回 sha256 版本；文件缺失 -> unversioned。"""
    try:
        if path.exists():
            return prompt_version(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return _UNVERSIONED
    return _UNVERSIONED
