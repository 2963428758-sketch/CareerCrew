"""阶段 C 可视化 demo：3 层记忆系统。

跑法：conda run -n careercrew python scripts/demo_memory.py
展示：
  1) episodic append-only JSONL + parentId 树（C2）+ memory_write 工具（C6）-- 写事件，看文件
  2) rebuild_context 从叶子回溯到根（C3）-- 打印上下文链
  3) User Model 结构化读写（C5）+ profile_update 工具（C6）-- 看画像文件 + 非法字段拒绝

数据写 data/demo_c/（已 gitignore，可重复跑会清空重写）。
"""
from __future__ import annotations

import json
from pathlib import Path

from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.user_model import UserModelStore
from careercrew_core.tools.internal.memory_write import make_memory_write_tool
from careercrew_core.tools.internal.profile_update import make_profile_update_tool

DEMO_DIR = Path("data/demo_c")


def show_episodic() -> None:
    print("=" * 64)
    print("1) episodic append-only JSONL + parentId 树（C2）+ memory_write 工具（C6）")
    print("=" * 64)
    path = DEMO_DIR / "transcripts/demo_user/demo_thread.jsonl"
    em = EpisodicMemory(path)
    path.write_text("", encoding="utf-8")  # 清空重跑
    write = make_memory_write_tool(em)

    print("\n写入 4 个事件（会话/匹配/面试/投递，parentId 自动接链）：")
    print(" ", write.invoke({"type": "session_start", "content": {"intent": "找大模型应用岗位"}}))
    print(" ", write.invoke({"type": "job_match", "content": {"company": "字节跳动", "title": "大模型应用工程师", "score": 0.88}}))
    print(" ", write.invoke({"type": "interview_qa", "content": {"q": "讲讲 RAG 的检索流程", "a": "query->召回->rerank->生成", "score": 8}}))
    print(" ", write.invoke({"type": "application", "content": {"company": "字节跳动", "status": "submitted"}}))

    print(f"\nJSONL 文件（{path}）每行一条，parentId 接链：")
    for line in path.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        print(f"  {e['id']} (parent={e['parentId']}) {e['type']}: {e['content']}")

    print("\n2) rebuild_context 从最新叶子回溯到根（C3）：")
    chain = em.rebuild_context(em.latest().id)
    for e in chain:
        print(f"  {e.id} -> {e.type}: {e.content}")
    print(f"  （共 {len(chain)} 条，root={chain[0].id}，leaf={chain[-1].id}）")


def show_user_model() -> None:
    print("\n" + "=" * 64)
    print("3) User Model 结构化读写（C5）+ profile_update 工具（C6）")
    print("=" * 64)
    store = UserModelStore(DEMO_DIR / "user_model.json")
    if store.path.exists():
        store.path.unlink()  # 清空重跑
    upd = make_profile_update_tool(store, user_id="demo_user")

    print("\n更新画像 / 目标公司 / 薪资偏好：")
    print(" ", upd.invoke({"fields": {"profile.skills": ["Python", "LangGraph", "RAG"], "profile.level": "中级", "profile.direction": "大模型应用/Agent"}}))
    print(" ", upd.invoke({"fields": {"target_companies": ["字节跳动", "阿里", "美团"]}}))
    print(" ", upd.invoke({"fields": {"preferences.salary_min": 30, "preferences.city": ["北京", "上海"]}}))

    print(f"\nUser Model 文件（{store.path}）：")
    print(store.path.read_text(encoding="utf-8"))

    print("\n非法字段拒绝：")
    print(" ", upd.invoke({"fields": {"profile.evil": "x"}}))


if __name__ == "__main__":
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    show_episodic()
    show_user_model()
    print("\n" + "=" * 64)
    print("append-only 树保证历史可完整回放 -> 轨迹级评估（黄金回放）的基础。")
    print("=" * 64)
