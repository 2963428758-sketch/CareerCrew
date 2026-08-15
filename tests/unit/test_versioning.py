"""T1.5：versioning 单元测试 —— prompt 版本 sha256 格式 / git-sha agent 版本 / 惰性 registry。

覆盖：
- prompt_version 格式（sha256:+64hex 小写）、确定性（同输入同输出、不同输入不同输出）、
  空文本/None -> unversioned。
- agent_version：env 变量注入、git 不可用（monkeypatch subprocess 抛异常）-> unversioned、
  模块级缓存（两次调用同值）、绝不返回 "unknown"。
- prompt_version_for_agent registry：6 个 agent_id + interviewer_chat 均返回 sha256:…，
  且与各自 prompt 文件的 sha256 一致；未知 agent_id -> unversioned。
"""
from __future__ import annotations

import hashlib
import re

import pytest

from careercrew_core import versioning

_SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@pytest.fixture(autouse=True)
def _reset_version_cache():
    """每个用例前后清 agent_version 模块级缓存，避免跨用例污染。"""
    versioning._cached_agent_version = None
    yield
    versioning._cached_agent_version = None


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── prompt_version ──


def test_prompt_version_format():
    assert _SHA_RE.match(versioning.prompt_version("hello"))


def test_prompt_version_deterministic():
    assert versioning.prompt_version("hello") == versioning.prompt_version("hello")
    assert versioning.prompt_version("你好世界") == _sha256("你好世界")


def test_prompt_version_distinct_inputs():
    assert versioning.prompt_version("a") != versioning.prompt_version("b")


def test_prompt_version_empty_and_none_unversioned():
    assert versioning.prompt_version("") == "unversioned"
    assert versioning.prompt_version(None) == "unversioned"
    assert versioning.prompt_version("   ") == "unversioned"


def test_prompt_version_hashes_utf8_bytes():
    """UTF-8 编码后哈希：非 ascii 内容与 hash 函数一致。"""
    text = "职位匹配官 prompt"
    assert versioning.prompt_version(text) == _sha256(text)


# ── agent_version ──


def test_agent_version_env_var_wins(monkeypatch):
    monkeypatch.setenv("CAREERCREW_AGENT_VERSION", "abc123def")
    versioning._cached_agent_version = None
    assert versioning.agent_version() == "abc123def"


def test_agent_version_env_var_blank_falls_back(monkeypatch):
    monkeypatch.setenv("CAREERCREW_AGENT_VERSION", "   ")
    versioning._cached_agent_version = None
    v = versioning.agent_version()
    # blank 视为缺失 -> 走 git 或 unversioned，但绝不等于空白值或 "unknown"
    assert v != "   "
    assert v != "unknown"


def test_agent_version_git_failure_returns_unversioned(monkeypatch):
    import subprocess

    def boom(*args, **kwargs):
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.delenv("CAREERCREW_AGENT_VERSION", raising=False)
    versioning._cached_agent_version = None
    assert versioning.agent_version() == "unversioned"


def test_agent_version_module_cache(monkeypatch):
    """两次调用仅在第一次跑 subprocess（第二次命中缓存，不重跑 git）。"""
    import subprocess

    calls = []

    class _FakeProc:
        returncode = 0
        stdout = "fake-git-sha-1234\n"

    def fake_run(*args, **kwargs):
        calls.append(args)
        return _FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.delenv("CAREERCREW_AGENT_VERSION", raising=False)
    versioning._cached_agent_version = None
    first = versioning.agent_version()
    second = versioning.agent_version()
    assert first == second == "fake-git-sha-1234"
    assert len(calls) == 1


def test_agent_version_never_unknown(monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    monkeypatch.delenv("CAREERCREW_AGENT_VERSION", raising=False)
    versioning._cached_agent_version = None
    assert versioning.agent_version() != "unknown"


# ── prompt_version_for_agent registry ──


def test_registry_all_known_keys_sha256():
    """6 个 agent_id + interviewer_chat 都返回 sha256:…。"""
    keys = [
        "job_matcher", "resume_advisor", "career_planner",
        "knowledge_advisor", "interviewer", "salary_negotiator",
        "interviewer_chat",
    ]
    for k in keys:
        v = versioning.prompt_version_for_agent(k)
        assert _SHA_RE.match(v), f"{k} -> {v}"


def test_registry_matches_prompt_file_sha256():
    from pathlib import Path

    root = Path(versioning.__file__).resolve().parents[1]
    mapping = {
        "job_matcher": "job_matcher.txt",
        "resume_advisor": "resume_advisor.txt",
        "career_planner": "career_planner.txt",
        "knowledge_advisor": "knowledge_advisor.txt",
        "interviewer": "interviewer.txt",
        "salary_negotiator": "salary_negotiator.txt",
        "interviewer_chat": "interviewer_chat.txt",
    }
    for agent_id, fname in mapping.items():
        text = (root / "careercrew_ai" / "prompts" / fname).read_text(encoding="utf-8")
        assert versioning.prompt_version_for_agent(agent_id) == _sha256(text), agent_id


def test_registry_unknown_agent_unversioned():
    assert versioning.prompt_version_for_agent("does_not_exist") == "unversioned"
    assert versioning.prompt_version_for_agent("") == "unversioned"
    assert versioning.prompt_version_for_agent(None) == "unversioned"
