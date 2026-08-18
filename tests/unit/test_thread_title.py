from __future__ import annotations

from types import SimpleNamespace

from careercrew_api.chat_lifecycle import TurnContext
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.conversation.db import FakeConversationDb
from careercrew_core.conversation.store import ConversationStore
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.threads import ThreadStore


class FakeLlm:
    def __init__(self, content: str = "目标岗位匹配与求职规划", error: Exception | None = None):
        self.content = content
        self.error = error
        self.calls = 0

    def invoke(self, _prompt: str):
        self.calls += 1
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.content)


def make_first_turn() -> tuple[CareerCrewRuntime, TurnContext]:
    runtime = CareerCrewRuntime()
    runtime._initialized = True
    runtime.memory_db = FakeMemoryDb()
    runtime.thread_store = ThreadStore(runtime.memory_db)
    runtime.conversation_store = ConversationStore(FakeConversationDb())
    conversation = runtime.conversation_store.ensure_conversation(
        "legacy-1", "u-1", "chat", title="我想找大模型工程师工作"
    )
    runtime.thread_store.upsert(
        "u-1", "legacy-1", title="我想找大模型工程师工作", module="chat"
    )
    turn = runtime.conversation_store.next_turn("legacy-1", "u-1")
    user = runtime.conversation_store.add_user_message(
        turn["id"], turn["thread_id"], "u-1", "我想找大模型工程师工作", "completed"
    )
    context = TurnContext(
        thread_id=conversation["id"],
        legacy_thread_id="legacy-1",
        turn_id=turn["id"],
        user_message_id=user["id"],
        assistant_message_id="assistant-1",
        run_id="run-1",
        module="chat",
        agent_id="career_planner",
        model="test",
        user_id="u-1",
    )
    return runtime, context


def test_first_turn_title_updates_conversation_and_memory_thread():
    runtime, context = make_first_turn()
    llm = FakeLlm()
    runtime.llm = llm

    runtime._maybe_generate_first_title(context, "建议先完善 RAG 项目经历，再匹配目标岗位。")

    assert llm.calls == 1
    assert runtime.conversation_store.get_conversation(context.thread_id, "u-1")["title"] == "目标岗位匹配与求职规划"
    assert runtime.thread_store.get("u-1", "legacy-1")["title"] == "目标岗位匹配与求职规划"


def test_title_generation_runs_only_for_first_turn():
    runtime, first = make_first_turn()
    second_turn = runtime.conversation_store.next_turn("legacy-1", "u-1")
    second_user = runtime.conversation_store.add_user_message(
        second_turn["id"], second_turn["thread_id"], "u-1", "再看看杭州岗位", "completed"
    )
    second = TurnContext(
        **{**first.__dict__, "turn_id": second_turn["id"], "user_message_id": second_user["id"]}
    )
    llm = FakeLlm()
    runtime.llm = llm

    runtime._maybe_generate_first_title(second, "补充了杭州岗位建议。")

    assert llm.calls == 0


def test_title_generation_failure_keeps_original_user_title():
    runtime, context = make_first_turn()
    runtime.llm = FakeLlm(error=RuntimeError("model unavailable"))

    runtime._maybe_generate_first_title(context, "回答内容")

    assert runtime.thread_store.get("u-1", "legacy-1")["title"] == "我想找大模型工程师工作"
