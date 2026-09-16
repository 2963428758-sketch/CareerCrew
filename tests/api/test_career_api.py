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
    client.post("/api/career/followups", json={
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
    metrics = client.get('/api/career/generation-metrics', params={'feature': 'application_kit'}).json()
    assert metrics['total'] == 2
    assert metrics['by_source'] == {'llm': 1, 'template': 1}
    assert metrics['fallback_count'] == 1


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


def test_share_lifecycle(career_api):
    """只读分享（令牌哈希入库）：明文仅创建时返回一次；公开访问带审计与防爬头；
    默认脱敏；撤销后 404。"""
    client, store, _ = career_api
    oid = _create_opp(client)
    version = client.post(f"/api/preparation/opportunities/{oid}/versions",
                          json={"label": "分享版本",
                                "content": (
                                    "联系我：13800001234 / me@x.com / 010-87654321，"
                                    "身份证 110101199003074258，微信号：career_2026，"
                                    "地址：北京市朝阳区建国路88号"
                                )}).json()

    # 整包分享：默认 mask_pii=True
    resp = client.post("/api/career/shares", json={"kind": "opportunity", "ref_id": oid})
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]
    assert resp.json()["mask_pii"] is True
    # 数据库不存明文，只存哈希
    rows = store.list_shares("u_001")
    assert rows and "token" not in rows[0]

    pub = client.get(f"/api/career/share/{token}")
    assert pub.status_code == 200
    assert pub.json()["company"] == "测试公司"
    assert pub.headers["cache-control"].startswith("no-store")
    assert pub.headers["x-robots-tag"] == "noindex, nofollow"
    # 访问审计：计数已递增
    assert store.list_shares("u_001")[0]["access_count"] == 1

    # 单版本分享 + 脱敏：手机/邮箱/座机/身份证/微信/地址全部隐藏
    resp = client.post("/api/career/shares", json={
        "kind": "resume_version", "ref_id": version["id"], "mask_pii": True})
    assert resp.status_code == 201
    masked = client.get(f"/api/career/share/{resp.json()['token']}")
    content = masked.json()["content"]
    assert "13800001234" not in content and "[手机号已隐藏]" in content
    assert "me@x.com" not in content and "[邮箱已隐藏]" in content
    assert "010-87654321" not in content and "[电话已隐藏]" in content
    assert "110101199003074258" not in content and "[证件号已隐藏]" in content
    assert "career_2026" not in content and "[微信号已隐藏]" in content
    assert "北京市朝阳区建国路88号" not in content and "[地址已隐藏]" in content

    # 撤销 → 公开访问 404
    assert client.delete(f"/api/career/shares/{token}").status_code == 200
    assert client.get(f"/api/career/share/{token}").status_code == 404
    assert client.get("/api/career/share/no-such-token").status_code == 404
    # 非法 kind / 越界有效期
    assert client.post("/api/career/shares", json={"kind": "bad", "ref_id": oid}).status_code == 422
    assert client.post("/api/career/shares", json={"kind": "opportunity", "ref_id": oid, "expires_days": 99}).status_code == 422


def test_public_share_rate_limit_is_bounded(career_api, monkeypatch):
    """公开读取按 IP 限流；超限响应仍带隐私头且不会暴露令牌。"""
    from careercrew_api.routers import career_shares

    client, _, _ = career_api
    oid = _create_opp(client)
    token = client.post("/api/career/shares", json={
        "kind": "opportunity", "ref_id": oid,
    }).json()["token"]
    monkeypatch.setattr(career_shares, "_SHARE_RATE_LIMIT", 2)
    career_shares._share_rate_bucket.clear()
    try:
        assert client.get(f"/api/career/share/{token}").status_code == 200
        assert client.get(f"/api/career/share/{token}").status_code == 200
        limited = client.get(f"/api/career/share/{token}")
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        assert "no-store" in limited.headers["cache-control"]
    finally:
        career_shares._share_rate_bucket.clear()


def test_intel_brief_template_and_llm(career_api, fake_runtime):
    """情报包：LLM 可用用语义生成，否则模板兜底；始终带「需自行核实」声明。"""
    client, _, _ = career_api
    oid = _create_opp(client)
    fake_runtime.orchestrator_override = lambda prompt, config=None: type(
        "R", (), {"content": '{"company_research": "推断：该公司做企业知识库", '
                            '"likely_questions": ["讲讲 RAG 项目"], '
                            '"confirm_questions": ["团队多大？"], "evidence": ["+18%"]}'})()
    resp = client.post(f"/api/career/opportunities/{oid}/intel-brief", json={})
    assert resp.status_code == 201, resp.text
    assert resp.json()["source"] == "llm"
    assert "未经核实" in resp.json()["disclaimer"]

    fake_runtime.orchestrator_override = lambda prompt, config=None: type(
        "R", (), {"content": "无法解析"})()
    resp = client.post(f"/api/career/opportunities/{oid}/intel-brief", json={})
    assert resp.json()["source"] == "template"
    assert resp.json()["confirm_questions"]


def test_applied_version_attribution(career_api):
    """版本归因：看板更新标记投递版本 → stats by_version 按版本细分。"""
    client, _, _ = career_api
    oid = _create_opp(client)
    version = client.post(f"/api/preparation/opportunities/{oid}/versions",
                          json={"label": "归因版本", "content": "正文"}).json()
    client.put(f"/api/career/board/{oid}", json={
        "stage": "已投递", "applied_version_id": version["id"]})
    stats = client.get("/api/career/stats").json()
    assert stats["by_version"]["归因版本"]["by_stage"]["已投递"] == 1


def test_contact_reminders_and_ics(career_api):
    """联系人提醒联动：下次联系时间进入提醒与 ICS。"""

    client, _, _ = career_api
    client.post("/api/career/contacts", json={
        "contact_name": "王内推", "company": "测试公司", "next_contact_date": "2026-08-01"})
    items = client.get("/api/career/reminders").json()["items"]
    assert any(i["kind"] == "contact_overdue" and "王内推" in i["title"] for i in items)
    ics = client.get("/api/career/reminders/ics").text
    assert "[联系] 测试公司 王内推" in ics


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
    assert resp.json()["opportunities"][0]["company"] == "测试公司"
    assert resp.json()["opportunities"][0]["jd"] == "负责接口开发"
    assert client.get("/api/career/search", params={"q": " "}).status_code == 422


def test_share_can_be_revoked_from_history_without_bearer_token(career_api):
    client, store, _ = career_api
    oid = _create_opp(client)
    created = client.post('/api/career/shares', json={'kind': 'opportunity', 'ref_id': oid}).json()
    history = client.get('/api/career/shares').json()[0]
    assert history['id'] == created['id']
    assert 'token' not in history and 'token_hash' not in history
    assert client.get('/api/career/share/' + history['id']).status_code == 404
    assert client.delete('/api/career/shares/' + history['id']).status_code == 200
    assert client.get('/api/career/share/' + created['token']).status_code == 404


def test_share_error_responses_have_privacy_headers(career_api):
    client, _, _ = career_api
    response = client.get('/api/career/share/missing')
    assert response.status_code == 404
    assert 'no-store' in response.headers['cache-control']
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['referrer-policy'] == 'no-referrer'


def test_search_cursor_pages_and_query_scope(career_api):
    import base64
    import json

    from careercrew_api.auth.dependencies import get_current_user

    client, _, _ = career_api
    for _ in range(3):
        _create_opp(client)
    first = client.get('/api/career/search', params={'q': '测试', 'limit': 2}).json()
    assert len(first['items']) == 2 and first['next_cursor']
    second = client.get('/api/career/search', params={'q': '测试', 'limit': 2, 'cursor': first['next_cursor']}).json()
    assert len(second['items']) == 1 and second['next_cursor'] is None
    assert {r['id'] for r in first['items']}.isdisjoint(r['id'] for r in second['items'])
    assert client.get('/api/career/search', params={'q': 'other', 'cursor': first['next_cursor']}).status_code == 422
    decoded = json.loads(base64.urlsafe_b64decode(
        first['next_cursor'] + '=' * (-len(first['next_cursor']) % 4),
    ))
    decoded[-1] = 'forged-position'
    forged = base64.urlsafe_b64encode(json.dumps(decoded).encode()).decode().rstrip('=')
    assert client.get('/api/career/search', params={'q': '测试', 'cursor': forged}).status_code == 422
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "bob", "role": "user"}
    assert client.get('/api/career/search', params={
        'q': '测试', 'cursor': first['next_cursor'],
    }).status_code == 422
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_001", "role": "admin"}
    assert client.get('/api/career/search', params={'q': '测试', 'limit': 51}).status_code == 422


def test_product_events_validate_deduplicate_and_purge(career_api):
    from careercrew_api.auth.dependencies import get_current_user

    client, store, _ = career_api
    payload = {'event': 'share_panel_opened', 'event_id': 'a90b7587-9e21-41e7-bb92-38612d861017', 'source': 'preparation'}
    assert client.post('/api/career/events', json=payload).status_code == 201
    assert client.post('/api/career/events', json=payload).status_code == 201
    assert client.post('/api/career/events', json={**payload, 'resume': 'private'}).status_code == 422
    assert client.post('/api/career/events', json={**payload, 'event': 'made_up'}).status_code == 422
    metrics = client.get('/api/career/events/funnel').json()
    assert metrics['counts']['share_panel_opened'] == 1
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "bob", "role": "user"}
    assert client.get('/api/career/events/funnel').json()['counts'] == {}
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_001", "role": "admin"}
    assert client.post('/api/career/privacy/purge').status_code == 200
    assert client.get('/api/career/events/funnel').json()['counts'].get('share_panel_opened', 0) == 0
