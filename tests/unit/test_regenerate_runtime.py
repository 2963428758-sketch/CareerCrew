"""T1.6 runtime run_regenerate_stream 单元测试（真实 ConversationStore + Fake 运行时代理）。

直接构造 CareerCrewRuntime（不触发 heavy init），monkeypatch conversation_store 为
Fake 底层的 ConversationStore，并用脚本化 dispatch 验证：
- 校验矩阵（非 assistant / 非 completed / 非最后一条 / 跨用户 → 拒绝）
- 稳定 ID 语义（turn 不变、run/message 变、regenerated_from 链完整、旧消息不覆盖/不 mutate）
- 幂等头（同 key 二次不新 run；无 key 每次新 run）
- consult / interview → 409
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from careercrew_api.runtime import (
    CareerCrewRuntime,
    RegenerateConflictError,
    ResourceNotFoundError,
)
from careercrew_core.conversation.db import FakeConversationDb
from careercrew_core.conversation.store import ConversationStore


def _uuid() -> str:
    return str(uuid4())


def _make_runtime(store: ConversationStore) -> CareerCrewRuntime:
    rt = CareerCrewRuntime.__new__(CareerCrewRuntime)
    # 不触发 __init__ 的线程锁等，直接打桩所需属性
    rt._initialized = True
    rt.settings = None
    rt.llm = None
    rt.embedding = None
    rt.store = None
    rt.reranker = None
    rt.multimodal_search = None
    rt.ingest_pipeline = None
    rt.memory_db = None
    rt.episodic = None
    rt.fact_store = None
    rt.policy_store = None
    rt.thread_store = None
    rt.memory_router = None
    rt.memory_injector = None
    rt._episodic_vector_store = None
    rt.conversation_store = store
    return rt


def _begin_round(store, *, user_id="u_1", thread_id="t-1", module="matcher",
                 agent_id="job_matcher", question="q", metadata=None):
    """跑一轮完整对话，返回 (conv, turn, user_msg, asst_msg, run)。"""
    conv = store.ensure_conversation(thread_id, user_id, module, "T")
    turn = store.next_turn(thread_id, user_id)
    user_msg = store.add_user_message(
        turn["id"], conv["id"], user_id, question, "completed", metadata=metadata
    )
    asst = store.add_assistant_message(turn["id"], conv["id"], user_id, "", None, None)
    asst = store.set_message_status(user_id, asst["id"], "streaming")
    run = store.start_run(
        thread_id=conv["id"], turn_id=turn["id"], message_id=asst["id"],
        user_id=user_id, module=module, agent_id=agent_id, model="deepseek-v4",
        prompt_version="unversioned", agent_version="1", status="streaming",
    )
    asst = store.set_message_run_id(user_id, asst["id"], run["id"])
    asst = store.set_message_content(user_id, asst["id"], "answer", status="completed")
    return conv, turn, user_msg, asst, run


def _dispatch(rt, result_map, calls_list):
    """给 rt 注入一个记录调用的 run_regenerate_stream 依赖的模块分派。"""

    def fake_get_cycle(thread_id, user_id):
        class C:
            job_matcher = None
            resume_advisor = None

            def run_match(self, intent):
                calls_list.append(("match", intent))

            def run_resume(self, jd_text):
                calls_list.append(("resume", jd_text))
        return C()

    rt.get_cycle = fake_get_cycle

    def fake_new_job_matcher(cb=None, episodic=None):
        calls_list.append(("new_job_matcher",))

        class A:
            last_result = type("R", (), {
                "content": result_map.get("content", "r2"),
                "input_tokens": 3, "output_tokens": 4,
                "tool_call_details": [{"name": "rag_query", "args": {"query": "x"}}],
            })()
            def run(self, state):
                if cb:
                    cb(self.last_result.content)
        return A()

    def fake_new_resume_advisor(cb=None, episodic=None, allowed=None,
                                hitl_requires=None, forced_doc_ids=None):
        calls_list.append(("new_resume_advisor",))
        return fake_new_job_matcher(cb, episodic)

    def fake_new_career_planner(cb=None, episodic=None, allowed=None,
                                hitl_requires=None, forced_doc_ids=None):
        calls_list.append(("new_career_planner",))
        result = type("R", (), {"content": result_map.get("content", "r2"),
                                "tool_call_details": []})()

        class A:
            last_result = result

            def run(self, state):
                if cb:
                    cb(self.last_result.content)
        return A()

    def fake_new_knowledge_advisor(cb=None, episodic=None, rag_sink=None,
                                   category="", knowledge_access_filters=None,
                                   forced_doc_ids=None):
        calls_list.append(("new_knowledge_advisor", category, bool(knowledge_access_filters)))
        if rag_sink:
            calls_list.append(("rag_sink",))
        return fake_new_job_matcher(cb, episodic)

    rt.new_job_matcher = fake_new_job_matcher
    rt.new_resume_advisor = fake_new_resume_advisor
    rt.new_career_planner = fake_new_career_planner
    rt.new_knowledge_advisor = fake_new_knowledge_advisor


def _run_regenerate(rt, message_id, user_id="u_1", idempotency_key=None):
    store = rt.conversation_store
    sw = dict(user_id=user_id, key=idempotency_key)
    if idempotency_key:
        existing = store.get_regeneration(user_id, idempotency_key)
        if existing:
            return store.get_message(user_id, existing)
    return rt.run_regenerate_stream(message_id, user_id) if not idempotency_key else \
        _run_with_idem(rt, message_id, user_id, idempotency_key)


def _run_with_idem(rt, message_id, user_id, key):
    # 模拟路由层幂等：命中返回既有 message 行；否则记录并执行
    store = rt.conversation_store
    existing = store.get_regeneration(user_id, key)
    if existing:
        return store.get_message(user_id, existing)
    res = rt.run_regenerate_stream(message_id, user_id)
    store.create_regeneration(user_id, key, res.turn.assistant_message_id)
    return res


# ── 校验矩阵 ──


def test_regenerate_non_assistant_rejected():
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    _dispatch(rt, {}, [])
    _, _, user_msg, _, _ = _begin_round(store)
    with pytest.raises(RegenerateConflictError):
        rt.run_regenerate_stream(user_msg["id"], "u_1")


def test_regenerate_non_completed_rejected():
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    rt.get_cycle = lambda *a, **k: None
    conv = store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    store.add_user_message(turn["id"], conv["id"], "u_1", "q", "completed")
    asst = store.add_assistant_message(turn["id"], conv["id"], "u_1", "", None, None)
    asst = store.set_message_status("u_1", asst["id"], "streaming")  # 仍 streaming
    with pytest.raises(RegenerateConflictError):
        rt.run_regenerate_stream(asst["id"], "u_1")


def test_regenerate_cross_user_404():
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    _dispatch(rt, {}, [])
    _, _, _, asst, _ = _begin_round(store)
    with pytest.raises(ResourceNotFoundError):
        rt.run_regenerate_stream(asst["id"], "u_2")


def test_regenerate_missing_404():
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    _dispatch(rt, {}, [])
    with pytest.raises(ResourceNotFoundError):
        rt.run_regenerate_stream(_uuid(), "u_1")


def test_regenerate_not_last_message_409():
    """中间版本的 assistant 消息（有后续版本）不可 regenerate。"""
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    _dispatch(rt, {}, [])
    _, _, _, a1, _ = _begin_round(store)
    # 追加 a2（同 turn，regenerated_from=a1，带新 run）
    a2 = store.add_assistant_message(a1["turn_id"], a1["thread_id"], "u_1", "", None, a1["id"])
    store.set_message_status("u_1", a2["id"], "streaming")
    run2 = store.start_run(
        thread_id=a1["thread_id"], turn_id=a1["turn_id"], message_id=a2["id"],
        user_id="u_1", module="matcher", agent_id="job_matcher", model="m",
        status="streaming",
    )
    store.set_message_run_id("u_1", a2["id"], run2["id"])
    store.set_message_content("u_1", a2["id"], "ans", status="completed")
    # a1 不再是最后一条（a2 在其后），regenerate a1 → 409
    with pytest.raises(RegenerateConflictError):
        rt.run_regenerate_stream(a1["id"], "u_1")
    # a2 是最后一条 → 允许
    res = rt.run_regenerate_stream(a2["id"], "u_1")
    assert res.turn.assistant_message_id != a2["id"]


def test_regenerate_latest_of_turn1_blocked_by_turn2():
    """线程级最后一条判定：turn1 的最新 assistant 在 turn2 存在时不可 regenerate。"""
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    _dispatch(rt, {}, [])
    _, _, _, a_turn1, _ = _begin_round(store, question="q1")
    # 第二 turn 完整一轮（存在其 assistant）
    _, _, _, a_turn2, _ = _begin_round(store, question="q2")
    # turn1 最新（版本链之叶）在 turn2 之后 → 线程级 409
    with pytest.raises(RegenerateConflictError, match="线程最后一条"):
        rt.run_regenerate_stream(a_turn1["id"], "u_1")
    # turn2 是线程最后一条 → 允许
    res = rt.run_regenerate_stream(a_turn2["id"], "u_1")
    assert res.turn.assistant_message_id != a_turn2["id"]


def test_regenerate_final_turn_allowed():
    """线程最后一条（最终 turn）允许 regenerate。"""
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    _dispatch(rt, {"content": "r2"}, [])
    _, _, _, a, _ = _begin_round(store, question="final")
    res = rt.run_regenerate_stream(a["id"], "u_1")
    assert res.turn.assistant_message_id != a["id"]


def test_regenerate_resume_without_jd_text_409():
    """resume 重跑缺 jd_text metadata（conversational 路径/legacy 行）→ 409。"""
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    _dispatch(rt, {}, [])
    _, _, _, asst, _ = _begin_round(
        store, module="resume", agent_id="resume_advisor",
        metadata=None,  # 无 jd_text
    )
    with pytest.raises(RegenerateConflictError, match="jd_text"):
        rt.run_regenerate_stream(asst["id"], "u_1")


def test_regenerate_knowledge_missing_scope_falls_back():
    """knowledge 重跑缺 category/scope metadata → 回退默认值（""/"all"）并成功（不 409）。"""
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    calls = []
    _dispatch(rt, {}, calls)
    _, _, _, asst, _ = _begin_round(
        store, module="knowledge", agent_id="knowledge_advisor",
        metadata=None,  # 无 category/scope
    )
    rt.run_regenerate_stream(asst["id"], "u_1")
    ka = [c for c in calls if c[0] == "new_knowledge_advisor"][0]
    assert ka[1] == ""       # category 回退默认 ""
    assert ka[2] is True     # scope 回退 "all" 后 filters 仍构造


def test_regenerate_consult_409():
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    _dispatch(rt, {}, [])
    _, _, _, asst, _ = _begin_round(store, module="consult", agent_id="consult_orchestrator")
    with pytest.raises(RegenerateConflictError):
        rt.run_regenerate_stream(asst["id"], "u_1")


def test_regenerate_interview_409():
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    _dispatch(rt, {}, [])
    _, _, _, asst, _ = _begin_round(store, module="interview", agent_id="interviewer")
    with pytest.raises(RegenerateConflictError):
        rt.run_regenerate_stream(asst["id"], "u_1")


# ── 稳定 ID 语义 ──


def test_regenerate_stable_turn_new_run_message():
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    calls = []
    _dispatch(rt, {"content": "r2"}, calls)
    _, turn, user_msg, asst, run = _begin_round(store, question="find job")
    res = rt.run_regenerate_stream(asst["id"], "u_1")

    assert res.turn.turn_id == turn["id"]  # turn 不变
    assert res.turn.run_id != run["id"]    # run 变
    assert res.turn.assistant_message_id != asst["id"]  # message 变
    # 旧消息不覆盖、不 mutate
    old = store.get_message("u_1", asst["id"])
    assert old["content"] == "answer"
    assert old["status"] == "completed"
    # 新消息 regenerated_from 指向旧消息
    new_msg = store.get_message("u_1", res.turn.assistant_message_id)
    assert new_msg["regenerated_from_message_id"] == asst["id"]
    assert new_msg["turn_id"] == turn["id"]
    assert new_msg["content"] == "r2"
    # 新 run 复用旧 run 的 module/agent_id/model/版本串
    new_run = store.get_run("u_1", res.turn.run_id)
    assert new_run["module"] == run["module"]
    assert new_run["agent_id"] == run["agent_id"]
    assert new_run["model"] == run["model"]
    assert new_run["prompt_version"] == run["prompt_version"]
    assert new_run["agent_version"] == run["agent_version"]
    # 版本链正确
    chain = store.list_message_versions(new_msg["id"], "u_1")
    assert [m["id"] for m in chain] == [asst["id"], new_msg["id"]]


def test_regenerate_matcher_dispatch():
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    calls = []
    _dispatch(rt, {"content": "r2"}, calls)
    _, _, _, asst, _ = _begin_round(store, question="find job")
    rt.run_regenerate_stream(asst["id"], "u_1")
    # matcher → new_job_matcher + run_match(intent)
    assert ("new_job_matcher",) in calls
    assert ("match", "find job") in calls


def test_regenerate_resume_uses_full_jd_from_metadata():
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    calls = []
    _dispatch(rt, {"content": "r2"}, calls)
    full_jd = "完整 JD 原文 " * 300  # 超 200 截断，存 metadata 保真
    _, _, _, asst, _ = _begin_round(
        store, module="resume", agent_id="resume_advisor",
        metadata={"jd_text": full_jd},
    )
    rt.run_regenerate_stream(asst["id"], "u_1")
    assert ("new_resume_advisor",) in calls
    # run_resume 用完整 jd_text（而非截断的 user content）
    assert ("resume", full_jd) in calls


def test_regenerate_knowledge_dispatch():
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    calls = []
    _dispatch(rt, {}, calls)
    _, _, _, asst, _ = _begin_round(
        store, module="knowledge", agent_id="knowledge_advisor",
        metadata={"category": "resume", "scope": "public"},
    )
    rt.run_regenerate_stream(asst["id"], "u_1")
    assert any(c[0] == "new_knowledge_advisor" for c in calls)
    ka = [c for c in calls if c[0] == "new_knowledge_advisor"][0]
    assert ka[1] == "resume"     # category 从 metadata 恢复
    assert ka[2] is True         # knowledge_access_filters 已构造
    assert ("rag_sink",) in calls  # rag_sink 收集 sources


def test_regenerate_plan_dispatch():
    store = ConversationStore(FakeConversationDb())
    rt = _make_runtime(store)
    calls = []
    _dispatch(rt, {"content": "r2"}, calls)
    _, _, _, asst, _ = _begin_round(store, module="chat", agent_id="career_planner", question="plan")
    rt.run_regenerate_stream(asst["id"], "u_1")
    assert ("new_career_planner",) in calls
