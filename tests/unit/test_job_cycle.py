"""G2 JobCycle 工作流测试（注入 fake agent）。"""
from __future__ import annotations

from careercrew_cli.workflow.job_cycle import JobCycle
from careercrew_ui.cli.renderer import Renderer


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
    cycle = JobCycle(jm, ra, renderer=Renderer())

    def select_jd(match_out: str) -> str:
        assert "字节" in match_out
        return "字节跳动 大模型应用工程师 JD：Agent/RAG/Python"

    out = cycle.run("我是大模型方向，有 Java 背景，帮我找工作并定制简历", select_jd=select_jd)
    assert out == "定制简历完成，匹配度 0.97"
    assert jm.run_calls == 1
    assert ra.run_calls == 1


def test_job_cycle_skip_resume() -> None:
    jm = FakeAgent("匹配结果")
    ra = FakeAgent("简历")
    cycle = JobCycle(jm, ra, renderer=Renderer())
    out = cycle.run("帮我找工作", select_jd=lambda _out: None)  # 跳过简历
    assert out == "匹配结果"
    assert ra.run_calls == 0


def test_run_match_only() -> None:
    jm = FakeAgent("匹配结果")
    cycle = JobCycle(jm, FakeAgent("x"), renderer=Renderer())
    assert cycle.run_match("我的方向是大模型") == "匹配结果"
    assert jm.run_calls == 1


def test_run_resume_only() -> None:
    ra = FakeAgent("简历完成")
    cycle = JobCycle(FakeAgent("x"), ra, renderer=Renderer())
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

    cycle = JobCycle(RecAgent(), RecAgent(), renderer=Renderer())
    cycle.run_match("我要找 java 工作")
    cycle.run_resume("某 JD")
    assert len(seen) == 2
    resume_msgs = seen[1]
    assert any("我要找 java 工作" in str(m.content) for m in resume_msgs)
    assert any("按这个 JD 定制简历" in str(m.content) for m in resume_msgs)


def test_job_cycle_injects_profile_preamble(tmp_path) -> None:
    """UserModel 画像注入：有画像则 agent 上下文带画像。"""
    from careercrew_core.memory.user_model import UserModelStore

    um = UserModelStore(tmp_path / "um.json")
    um.update("u1", {"profile.skills": ["Java", "Spring"], "profile.direction": "Java 后端"})
    seen = []

    class RecAgent:
        def __init__(self):
            self.last_result = type("R", (), {"content": "out"})()

        def run(self, state):
            seen.append(list(state["messages"]))

    cycle = JobCycle(RecAgent(), RecAgent(), renderer=Renderer(), user_model_store=um, user_id="u1")
    cycle.run_match("帮我找工作")
    msgs = seen[0]
    assert any("[用户画像]" in str(m.content) and "Java" in str(m.content) for m in msgs)


def test_run_match_syncs_profile_from_intent(tmp_path) -> None:
    """用户最新消息的明确字段刷新画像：旧方向被新方向覆盖，避免历史画像带偏。"""
    from careercrew_core.memory.user_model import UserModelStore

    um = UserModelStore(tmp_path / "um.json")
    um.update("u1", {"profile.direction": "Java 后端", "profile.skills": ["Java"]})

    class FakeLLM:
        def invoke(self, messages, config=None):
            return type("R", (), {"content": '{"profile.direction": "大模型应用"}'})()

    class AgentWithLLM:
        def __init__(self):
            self.llm = FakeLLM()
            self.last_result = type("R", (), {"content": "匹配完成"})()
            self.run_calls = 0

        def run(self, state):
            self.run_calls += 1

    cycle = JobCycle(AgentWithLLM(), AgentWithLLM(), renderer=Renderer(), user_model_store=um, user_id="u1")
    cycle.run_match("我是大模型应用方向")
    m = um.load("u1")
    assert m.profile.direction == "大模型应用"  # 新方向覆盖旧 Java 方向


def test_run_match_keeps_profile_when_no_new_field(tmp_path) -> None:
    """消息里没给新字段时画像保持原样（不误清）。"""
    from careercrew_core.memory.user_model import UserModelStore

    um = UserModelStore(tmp_path / "um.json")
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

    cycle = JobCycle(AgentWithLLM(), AgentWithLLM(), renderer=Renderer(), user_model_store=um, user_id="u1")
    cycle.run_match("帮我找工作")
    assert um.load("u1").profile.direction == "大模型应用"
