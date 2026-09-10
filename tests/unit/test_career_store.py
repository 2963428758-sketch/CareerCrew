"""求职跟进域（迁移 0005）行为测试：owner 隔离、看板流转记录、级联删除。"""
import pytest

from careercrew_core.career.store import CareerStore
from careercrew_core.preparation.store import PreparationStore
from tests.preparation_fakes import SqliteCareerPool


@pytest.fixture
def stores():
    pool = SqliteCareerPool()
    prep = PreparationStore(pool=pool)
    career = CareerStore(pool=pool)
    opp = prep.create_opportunity("alice", {
        "company": "测试公司", "title": "Java开发", "jd": "负责接口开发"})
    yield type("Stores", (), {"prep": prep, "career": career, "opp": opp})
    pool.close()


@pytest.fixture
def store(stores):
    return stores.career


def test_board_defaults_and_owner_isolation(store, stores):
    board = store.list_board("alice")
    assert len(board) == 1 and board[0]["stage"] == "待准备"
    assert store.list_board("bob") == []
    assert store.get_board_row("bob", stores.opp["id"]) is None


def test_stage_transition_records_log(store, stores):
    updated = store.update_board("alice", stores.opp["id"], {
        "stage": "已投递", "next_action": "跟进 HR", "next_action_date": "2026-09-10",
        "note": "已内推"})
    assert updated["stage"] == "已投递"
    store.record_stage_change("alice", stores.opp["id"], "待准备", "已投递", "已内推")
    log = store.list_stage_changes("alice", stores.opp["id"])
    assert log[0]["from_stage"] == "待准备" and log[0]["to_stage"] == "已投递"
    assert store.list_stage_changes("bob", stores.opp["id"]) == []


def test_invalid_stage_and_date_rejected(store, stores):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        store.update_board("alice", stores.opp["id"], {"stage": "不存在的阶段"})
    with pytest.raises(ValidationError):
        store.update_board("alice", stores.opp["id"], {"stage": "已投递", "next_action_date": "09/10"})


def test_materials_crud_scoped(store, stores):
    material = store.create_material("alice", {"name": "RAG 项目", "results": "召回+12%",
                                               "tags": ["RAG", "Agent"], "confirmed": True})
    assert material["tags"] == ["RAG", "Agent"]
    updated = store.update_material("alice", material["id"], {
        "name": "RAG 项目二期", "confirmed": False})
    assert updated["name"] == "RAG 项目二期"
    assert len(store.list_materials("alice")) == 1
    assert store.list_materials("bob") == []
    assert store.update_material("bob", material["id"], {"name": "盗用"}) is None
    assert store.delete_material("alice", material["id"]) is True


def test_tasks_lifecycle(store, stores):
    task = store.create_task("alice", {"title": "改简历", "due_date": "2026-09-08",
                                       "opportunity_id": stores.opp["id"]})
    store.complete_task("alice", task["id"], True)
    store.postpone_task("alice", task["id"], "2026-09-20")
    rows = store.list_tasks("alice")
    assert rows[0]["due_date"] == "2026-09-20" and rows[0]["postponed_count"] >= 1
    store.dismiss_task("alice", task["id"], True)
    assert store.list_tasks("bob") == []
    assert store.delete_task("alice", task["id"]) is True


def test_followups_reply_draft_needs_confirmation(store, stores):
    row = store.create_followup("alice", {"company": "测试公司", "content": "约下周二面试",
                                          "channel": "Boss直聘", "todo_note": "确认时间"})
    assert not row["draft_confirmed"]
    store.set_reply_draft("alice", row["id"], {"reply_draft": "您好，周三下午可以", "confirmed": False})
    rows = store.list_followups("alice")
    assert rows[0]["reply_draft"].startswith("您好") and not rows[0]["draft_confirmed"]
    store.set_reply_draft("alice", row["id"], {"reply_draft": "您好，周三下午可以", "confirmed": True})
    assert store.list_followups("alice")[0]["draft_confirmed"]
    store.resolve_followup("alice", row["id"], True)
    assert store.delete_followup("bob", row["id"]) is False


def test_offers_scoped(store, stores):
    offer = store.create_offer("alice", {"company": "A公司", "base_salary": "30K"})
    assert store.update_offer("bob", offer["id"], {"company": "B"}) is None
    assert len(store.list_offers("alice")) == 1
    assert store.delete_offer("alice", offer["id"]) is True


def test_real_interview_weak_points_extracted(store, stores):
    record = store.create_real_interview("alice", {
        "company": "A公司", "interview_date": "2026-09-05",
        "questions": [
            {"question": "讲讲索引", "answer": "B+树", "reflection": "对回表理解不深"},
            {"question": "讲讲事务", "answer": "ACID"},
        ]})
    assert record["weak_points"] == ["对回表理解不深"]
    assert store.list_real_interviews("bob") == []


def test_stats_rates_have_denominators(store, stores):
    store.update_board("alice", stores.opp["id"], {"stage": "已投递"})
    store.record_stage_change("alice", stores.opp["id"], "待准备", "已投递")
    store.create_followup("alice", {"company": "测试公司", "content": "有回复"})
    store.create_task("alice", {"title": "准备面试"})
    stats = store.job_search_stats("alice")
    assert stats["applied"] == 1 and stats["replies"] == 1
    assert stats["reply_rate"]["denominator"] == 1
    assert stats["by_stage"]["已投递"] == 1
    assert stats["tasks"]["open"] == 1


def test_global_search_scoped(store, stores):
    store.create_material("alice", {"name": "RAG 项目"})
    result = store.global_search("alice", "RAG")
    assert len(result["materials"]) == 1
    assert store.global_search("bob", "RAG")["materials"] == []


def test_export_scoped(store, stores):
    exported = store.export_all("alice")
    assert exported["opportunities"][0]["company"] == "测试公司"


def test_purge_all_and_cascade(store, stores):
    store.create_material("alice", {"name": "RAG 项目"})
    store.create_task("alice", {"title": "改简历"})
    counts = store.purge_all("alice")
    assert counts["preparation_opportunities"] == 1
    assert counts["project_materials"] == 1
    assert store.export_all("alice")["opportunities"] == []
    assert store.export_all("alice")["tasks"] == []


def test_delete_opportunity_cascades_board_log(store, stores):
    store.record_stage_change("alice", stores.opp["id"], "待准备", "已投递")
    store.create_task("alice", {"title": "跟进", "opportunity_id": stores.opp["id"]})
    assert stores.prep.delete_opportunity("alice", stores.opp["id"]) is True
    assert store.list_stage_changes("alice", stores.opp["id"]) == []


def test_profile_upsert(store):
    assert store.get_profile("alice") is None
    store.upsert_profile("alice", {"stage": "在职看机会", "city": "深圳",
                                   "goal": "大模型应用", "onboarding_done": True})
    profile = store.get_profile("alice")
    assert profile["city"] == "深圳" and profile["onboarding_done"]
    store.upsert_profile("alice", {"stage": "离职求职", "city": "上海",
                                   "goal": "", "onboarding_done": True})
    assert store.get_profile("alice")["city"] == "上海"
