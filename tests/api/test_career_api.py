"""求职跟进 API 测试：owner 隔离、校验、看板流转、统计与隐私。"""
import pytest


@pytest.fixture
def career_api(client, monkeypatch):
    """在 FakeRuntime 客户端上注入 SQLite CareerStore，并让 prep 路由共用同一库。"""
    import careercrew_api.preparation_context as pc
    import careercrew_api.routers.career as career_router
    import careercrew_api.routers.preparation as prep_router
    from careercrew_core.career.store import CareerStore
    from careercrew_core.preparation.store import PreparationStore

    from tests.preparation_fakes import SqliteCareerPool

    pool = SqliteCareerPool()
    career_store = CareerStore(pool=pool)
    prep_store = PreparationStore(pool=pool)
    import careercrew_api.routers.career as cr

    monkeypatch.setattr(pc, "get_preparation_store", lambda: prep_store)
    monkeypatch.setattr(cr, "get_career_store", lambda: career_store)
    client.app.dependency_overrides[prep_router.get_preparation_store] = lambda: prep_store
    client.app.dependency_overrides[career_router._store_dep] = lambda: career_store
    yield client, career_store, prep_store
    client.app.dependency_overrides.pop(prep_router.get_preparation_store, None)
    client.app.dependency_overrides.pop(career_router._store_dep, None)
    pool.close()


def _create_opp(client):
    resp = client.post("/api/preparation/opportunities", json={
        "company": "测试公司", "title": "Java开发", "jd": "负责接口开发"})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_board_update_records_transition(career_api):
    client, _, _ = career_api
    oid = _create_opp(client)
    resp = client.get("/api/career/board")
    assert resp.status_code == 200 and resp.json()[0]["stage"] == "待准备"

    resp = client.put(f"/api/career/board/{oid}", json={
        "stage": "已投递", "next_action": "跟进 HR", "next_action_date": "2026-09-10"})
    assert resp.status_code == 200
    assert resp.json()["stage"] == "已投递"
    log = client.get(f"/api/career/board/{oid}/log").json()
    assert log[0]["from_stage"] == "待准备" and log[0]["to_stage"] == "已投递"

    # 校验：非法阶段 422；跨账号归档 404
    assert client.put(f"/api/career/board/{oid}", json={"stage": "乱写"}).status_code == 422
    assert client.put("/api/career/board/missing", json={"stage": "已投递"}).status_code == 404


def test_tasks_stats_and_privacy(career_api):
    client, _, _ = career_api
    resp = client.post("/api/career/tasks", json={"title": "改简历", "due_date": "2026-09-08"})
    assert resp.status_code == 201
    task_id = resp.json()["id"]
    assert client.post("/api/career/tasks", json={"title": " "}).status_code == 422
    assert client.patch(f"/api/career/tasks/{task_id}", json={}).status_code == 422
    assert client.patch(f"/api/career/tasks/{task_id}", json={"done": True}).status_code == 200
    assert client.patch("/api/career/tasks/missing", json={"done": True}).status_code == 404

    stats = client.get("/api/career/stats").json()
    assert stats["tasks"]["done"] == 1
    assert "reply_rate" in stats and "offer_rate" in stats

    export = client.get("/api/career/privacy/export").json()
    assert "opportunities" in export and "tasks" in export
    purge = client.post("/api/career/privacy/purge").json()
    assert purge["ok"] is True and "deleted" in purge
    assert client.get("/api/career/tasks").json() == []


def test_materials_and_offers_and_followups(career_api):
    client, _, _ = career_api
    resp = client.post("/api/career/materials", json={"name": "RAG 项目", "tags": ["RAG"]})
    assert resp.status_code == 201 and resp.json()["tags"] == ["RAG"]
    mid = resp.json()["id"]
    assert client.put(f"/api/career/materials/{mid}", json={"name": "RAG 二期"}).status_code == 200
    assert client.put(f"/api/career/materials/{mid}", json={"name": " "}).status_code == 422
    assert client.delete(f"/api/career/materials/{mid}").status_code == 200
    assert client.delete("/api/career/materials/missing").status_code == 404

    offer = client.post("/api/career/offers", json={"company": "A公司", "base_salary": "30K"})
    assert offer.status_code == 201
    assert client.get("/api/career/offers").json()[0]["base_salary"] == "30K"

    followup = client.post("/api/career/followups", json={
        "company": "A公司", "content": "约面试"})
    assert followup.status_code == 201
    fid = followup.json()["id"]
    draft = client.put(f"/api/career/followups/{fid}/reply-draft",
                       json={"reply_draft": "您好，可以参加", "confirmed": False})
    assert draft.status_code == 200 and not draft.json()["draft_confirmed"]
    assert client.post(f"/api/career/followups/{fid}/resolve").status_code == 200


def test_gap_analysis_rule_fallback(career_api, fake_runtime):
    """runtime LLM 输出不可解析时按规则拆解 JD 要求并判定证据。"""
    client, _, _ = career_api
    oid = _create_opp(client)
    # FakeLLM 走 orchestrator_override：输出非 JSON → 解析失败 → 规则兜底
    fake_runtime.orchestrator_override = lambda prompt, config=None: type(
        "R", (), {"content": "抱歉，暂时无法分析"})()
    resp = client.post(f"/api/career/opportunities/{oid}/gap-analysis", json={})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["result"]["source"] == "rules"
    items = client.get(f"/api/career/opportunities/{oid}/gap-analysis").json()
    assert items[0]["id"] == body["id"]
    # 跨账号 404
    from careercrew_api.auth.dependencies import get_current_user

    client.app.dependency_overrides[get_current_user] = lambda: {"id": "bob", "role": "user"}
    assert client.post(f"/api/career/opportunities/{oid}/gap-analysis", json={}).status_code == 404
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_001", "role": "admin"}
    assert client.get("/api/career/board").status_code == 200


def test_gap_analysis_uses_llm_when_available(career_api, fake_runtime):
    client, _, _ = career_api
    oid = _create_opp(client)
    version = client.post(f"/api/preparation/opportunities/{oid}/versions",
                          json={"label": "v1", "content": "我有 RAG 项目经验"}).json()
    fake_runtime.orchestrator_override = lambda prompt, config=None: type(
        "R", (), {"content": ('{"requirements": [{"requirement": "熟悉 RAG", "status": "matched",'
                              ' "evidence": "RAG 项目", "note": "有项目证据"}]}')})()
    resp = client.post(f"/api/career/opportunities/{oid}/gap-analysis",
                       json={"resume_version_id": version["id"]})
    assert resp.status_code == 201
    assert resp.json()["result"]["source"] == "llm"
    assert resp.json()["result"]["requirements"][0]["requirement"] == "熟悉 RAG"


def test_interview_review_from_thread_history(career_api, fake_runtime):
    """整场复盘：从面试线程历史抽取问答与分数，规则汇总存报告。"""
    client, career_store, _ = career_api
    # 准备一个含问答与评分的线程
    tid = "i-rev-1"
    store = fake_runtime.conversation_store
    store.ensure_conversation(tid, "u_001", "interview")
    turn = store.next_turn(tid, "u_001")
    store.add_user_message(turn["id"], tid, "u_001", "请出题", "completed")
    store.add_user_message(turn["id"], tid, "u_001", "答：我会用缓存和索引优化", "completed")
    asst = store.add_assistant_message(turn["id"], tid, "u_001", "", None, None)
    store.set_message_content("u_001", asst["id"],
                              "问题：如何优化慢查询？\n评分：8 分\n反馈：结构清晰", "completed")
    assert asst["id"]

    resp = client.post("/api/career/interview-review", json={"thread_id": tid})
    assert resp.status_code == 200, resp.text
    report = resp.json()["report"]
    assert report["source"] in ("rules", "llm")
    assert report["total_questions"] >= 1
    reports = client.get("/api/career/interview-reports", params={"thread_id": tid}).json()
    assert reports and reports[0]["thread_id"] == tid


def test_opportunity_timeline_aggregates_all_events(career_api):
    """岗位档案时间线：收藏/版本/会话/阶段流转/任务聚合为倒序事件流。"""
    client, _, _ = career_api
    oid = _create_opp(client)
    version = client.post(f"/api/preparation/opportunities/{oid}/versions",
                          json={"label": "时间线版本", "content": "简历正文"}).json()
    client.post(f"/api/preparation/opportunities/{oid}/sessions",
                json={"module": "interview", "resume_version_id": version["id"]})
    client.put(f"/api/career/board/{oid}", json={"stage": "已投递"})
    client.post("/api/career/tasks", json={"title": "跟进投递", "opportunity_id": oid})

    resp = client.get(f"/api/career/opportunities/{oid}/timeline")
    assert resp.status_code == 200, resp.text
    events = resp.json()["events"]
    kinds = [e["kind"] for e in events]
    assert "created" in kinds and "resume_version" in kinds
    assert "session" in kinds and "stage" in kinds and "task" in kinds
    # 倒序
    ats = [e["at"] for e in events if e["at"]]
    assert ats == sorted(ats, reverse=True)
    # 跨账号 404
    from careercrew_api.auth.dependencies import get_current_user

    client.app.dependency_overrides[get_current_user] = lambda: {"id": "bob", "role": "user"}
    assert client.get(f"/api/career/opportunities/{oid}/timeline").status_code == 404
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_001", "role": "admin"}


def test_reminders_and_ics(career_api):
    """提醒中心：任务逾期/到期、看板跟进、HR 待办聚合；ICS 导出为合法日历。"""
    import time as time_mod

    client, _, _ = career_api
    oid = _create_opp(client)
    today = time_mod.strftime("%Y-%m-%d")
    # 逾期任务 + 已完成任务（后者不提醒）
    client.post("/api/career/tasks", json={"title": "过期任务", "due_date": "2026-08-01"})
    client.post("/api/career/tasks", json={"title": "已完成任务", "due_date": "2026-08-01", })
    task_rows = client.get("/api/career/tasks").json()
    done_row = next(t for t in task_rows if t["title"] == "已完成任务")
    client.patch(f"/api/career/tasks/{done_row['id']}", json={"done": True})
    # 看板下一步动作
    client.put(f"/api/career/board/{oid}", json={
        "stage": "已投递", "next_action": "跟进 HR", "next_action_date": today})
    # HR 待办
    followup = client.post("/api/career/followups", json={
        "company": "测试公司", "content": "沟通", "todo_note": "确认时间"}).json()

    items = client.get("/api/career/reminders").json()["items"]
    kinds = [i["kind"] for i in items]
    assert "task_overdue" in kinds and "action_due" in kinds and "followup" in kinds
    assert all("已完成任务" not in i["title"] for i in items)

    ics = client.get("/api/career/reminders/ics")
    assert ics.status_code == 200
    assert ics.headers["content-type"].startswith("text/calendar")
    body = ics.text
    assert body.startswith("BEGIN:VCALENDAR") and "END:VCALENDAR" in body
    assert "[任务] 过期任务" in body and "[跟进] 测试公司 跟进 HR" in body


def test_ats_check_rule_only(career_api):
    """ATS 体检：确定性规则，不调用 LLM；简历缺联系方式/章节给出 warn。"""
    client, _, _ = career_api
    oid = _create_opp(client)
    version = client.post(f"/api/preparation/opportunities/{oid}/versions",
                          json={"label": "体检版本", "content": "只有一句话的简历"}).json()
    resp = client.post(f"/api/career/opportunities/{oid}/ats-check",
                       json={"resume_version_id": version["id"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "rules"
    items = {c["item"]: c["status"] for c in body["checks"]}
    assert items["联系方式：邮箱"] == "warn"
    assert items["章节：教育"] == "warn"
    assert body["jd_coverage"]["requirements"] >= 1


def test_application_kit_llm_and_template(career_api, fake_runtime):
    """材料包：LLM 输出可解析时用 LLM；否则模板兜底，五段齐全。"""
    client, _, _ = career_api
    oid = _create_opp(client)
    version = client.post(f"/api/preparation/opportunities/{oid}/versions",
                          json={"label": "kit版本", "content": "技能：Python、RAG；问答准确率 +18%"}).json()

    # LLM 路径
    fake_runtime.orchestrator_override = lambda prompt, config=None: type(
        "R", (), {"content": '{"cover_letter": "您好，看到岗位与我很匹配", "self_intro": "s",'
                            ' "greeting": "g", "followup": "f", "thank_you": "t"}'})()
    resp = client.post(f"/api/career/opportunities/{oid}/application-kit",
                       json={"resume_version_id": version["id"]})
    assert resp.status_code == 201
    assert resp.json()["source"] == "llm"
    assert "很匹配" in resp.json()["sections"]["cover_letter"]

    # 模板兜底（LLM 输出不可解析）
    fake_runtime.orchestrator_override = lambda prompt, config=None: type(
        "R", (), {"content": "无法解析"})()
    resp = client.post(f"/api/career/opportunities/{oid}/application-kit",
                       json={"resume_version_id": version["id"]})
    assert resp.json()["source"] == "template"
    sections = resp.json()["sections"]
    for key in ("cover_letter", "self_intro", "greeting", "followup", "thank_you"):
        assert sections[key].strip()


def test_stats_by_source_attribution(career_api):
    """效果归因：按岗位来源细分阶段分布与样本量。"""
    client, _, _ = career_api
    oid = client.post("/api/preparation/opportunities", json={
        "company": "测试公司", "title": "Java开发", "jd": "负责接口开发",
        "source": "内推"}).json()["id"]
    client.put(f"/api/career/board/{oid}", json={"stage": "已投递"})
    stats = client.get("/api/career/stats").json()
    assert "by_source" in stats
    boss = stats["by_source"]["内推"]
    assert boss["total"] == 1
    assert boss["by_stage"]["已投递"] == 1


def test_contacts_crud_scoped(career_api):
    """联系人管理：创建/更新/删除，跨账号 404。"""
    client, _, _ = career_api
    resp = client.post("/api/career/contacts", json={
        "contact_name": "王 HR", "company": "云帆科技", "role": "招聘者",
        "channel": "微信", "contact_value": "wx_12345", "notes": "内推人介绍"})
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    assert client.put(f"/api/career/contacts/{cid}", json={
        "contact_name": "王 HR", "next_contact_date": "2026-09-10"}).status_code == 200
    assert client.put(f"/api/career/contacts/{cid}", json={"contact_name": " "}).status_code == 422
    assert client.put("/api/career/contacts/missing", json={"contact_name": "x"}).status_code == 404
    assert client.delete(f"/api/career/contacts/{cid}").status_code == 200
    assert client.delete(f"/api/career/contacts/{cid}").status_code == 404


def test_profile_endpoints(career_api):
    client, _, _ = career_api
    assert client.get("/api/career/profile").json() is None
    resp = client.put("/api/career/profile", json={
        "stage": "在职看机会", "city": "深圳", "goal": "大模型应用", "onboarding_done": True})
    assert resp.status_code == 200
    assert client.get("/api/career/profile").json()["onboarding_done"]


def test_global_search_endpoint(career_api):
    client, _, _ = career_api
    _create_opp(client)
    resp = client.get("/api/career/search", params={"q": "测试公司"})
    assert resp.status_code == 200
    assert len(resp.json()["opportunities"]) == 1
    assert client.get("/api/career/search", params={"q": " "}).status_code == 422
