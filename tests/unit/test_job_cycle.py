"""G2 JobCycle 工作流测试（注入 fake agent）。"""
from __future__ import annotations

from careercrew_core.workflow.job_cycle import JobCycle


class FakeAgent:
    def __init__(self, content: str) -> None:
        self._content = content
        self.last_result = type("R", (), {"content": content})()
        self.run_calls = 0

    def run(self, state) -> None:
        self.run_calls += 1


def test_job_cycle_full_flow() -> None:
    jm = FakeAgent("匹配到字节 0.95 / 腾讯 0.85")
    ra = FakeAgent("定制简历完成，匹配度 0.97")
    cycle = JobCycle(jm, ra, user_id="u1")

    def select_jd(match_out: str) -> str:
        assert "字节" in match_out
        return "字节跳动 大模型应用工程师 JD：Agent/RAG/Python"

    out = cycle.run("我是大模型方向，有 Java 背景，帮我找工作并定制简历", user_id="u1", select_jd=select_jd)
    assert out == "定制简历完成，匹配度 0.97"
    assert jm.run_calls == 1
    assert ra.run_calls == 1


def test_job_cycle_skip_resume() -> None:
    jm = FakeAgent("匹配结果")
    ra = FakeAgent("简历")
    cycle = JobCycle(jm, ra, user_id="u1")
    out = cycle.run("帮我找工作", user_id="u1", select_jd=lambda _out: None)  # 跳过简历
    assert out == "匹配结果"
    assert ra.run_calls == 0


def test_run_match_only() -> None:
    jm = FakeAgent("匹配结果")
    cycle = JobCycle(jm, FakeAgent("x"), user_id="u1")
    assert cycle.run_match("我的方向是大模型") == "匹配结果"
    assert jm.run_calls == 1


def test_run_resume_only() -> None:
    ra = FakeAgent("简历完成")
    cycle = JobCycle(FakeAgent("x"), ra, user_id="u1")
    assert cycle.run_resume("某 JD 内容") == "简历完成"
    assert ra.run_calls == 1


def test_job_cycle_carries_conversation() -> None:
    """跨步骤对话携带：resume agent 能看到 match 环节的用户输入。"""
    seen = []

    class RecAgent:
        def __init__(self):
            self.last_result = type("R", (), {"content": "out"})()

        def run(self, state):
            seen.append(list(state["messages"]))

    cycle = JobCycle(RecAgent(), RecAgent(), user_id="u1")
    cycle.run_match("我要找 java 工作")
    cycle.run_resume("某 JD")
    assert len(seen) == 2
    resume_msgs = seen[1]
    assert any("我要找 java 工作" in str(m.content) for m in resume_msgs)
    assert any("按这个 JD 定制简历" in str(m.content) for m in resume_msgs)


def test_job_cycle_injects_profile_preamble() -> None:
    """UserModel 画像注入：有画像则 agent 上下文带画像。"""
    from careercrew_core.memory.db import FakeMemoryDb
    from careercrew_core.memory.semantic import SemanticFactStore

    um = SemanticFactStore(FakeMemoryDb(), user_id="u1")
    um.update("u1", {"profile.skills": ["Java", "Spring"], "profile.direction": "Java 后端"})
    seen = []

    class RecAgent:
        def __init__(self):
            self.last_result = type("R", (), {"content": "out"})()

        def run(self, state):
            seen.append(list(state["messages"]))

    cycle = JobCycle(RecAgent(), RecAgent(), user_model_store=um, user_id="u1")
    cycle.run_match("帮我找工作")
    msgs = seen[0]
    assert any("[用户画像]" in str(m.content) and "Java" in str(m.content) for m in msgs)


def test_run_match_delegates_profile_update_without_pre_llm_call() -> None:
    """画像更新交给 matcher 同轮工具调用，JobCycle 不再额外预调一次 LLM。"""
    from careercrew_core.memory.db import FakeMemoryDb
    from careercrew_core.memory.semantic import SemanticFactStore

    um = SemanticFactStore(FakeMemoryDb(), user_id="u1")
    um.update("u1", {"profile.direction": "Java 后端", "profile.skills": ["Java"]})

    class FakeLLM:
        def invoke(self, messages, config=None):
            raise AssertionError("JobCycle 不应在 matcher 前额外调用 LLM")

    class AgentWithLLM:
        def __init__(self):
            self.llm = FakeLLM()
            self.last_result = type("R", (), {"content": "匹配完成"})()
            self.run_calls = 0
            self.seen = None

        def run(self, state):
            self.run_calls += 1
            self.seen = state

    matcher = AgentWithLLM()
    cycle = JobCycle(matcher, AgentWithLLM(), user_model_store=um, user_id="u1")
    cycle.run_match("我是大模型应用方向")
    assert matcher.run_calls == 1
    assert any("我是大模型应用方向" in str(m.content) for m in matcher.seen["messages"])
    # fake matcher 没执行 profile_update，所以旧画像不应被 JobCycle 私自改写
    assert um.load("u1").profile.direction == "Java 后端"


def test_run_match_keeps_profile_when_no_new_field() -> None:
    """消息里没给新字段时画像保持原样（不误清）。"""
    from careercrew_core.memory.db import FakeMemoryDb
    from careercrew_core.memory.semantic import SemanticFactStore

    um = SemanticFactStore(FakeMemoryDb(), user_id="u1")
    um.update("u1", {"profile.direction": "大模型应用"})

    class FakeLLM:
        def invoke(self, messages, config=None):
            return type("R", (), {"content": "{}"})()

    class AgentWithLLM:
        def __init__(self):
            self.llm = FakeLLM()
            self.last_result = type("R", (), {"content": "ok"})()
        def run(self, state):
            pass

    cycle = JobCycle(AgentWithLLM(), AgentWithLLM(), user_model_store=um, user_id="u1")
    cycle.run_match("帮我找工作")
    assert um.load("u1").profile.direction == "大模型应用"
