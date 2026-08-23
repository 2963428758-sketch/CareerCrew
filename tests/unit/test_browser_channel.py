"""N1 浏览器通道单元测试：解析/风控探测/回退链，全部用 Fake 页面对象（无真浏览器）。

CDP 真实链路的手动验收见 docs/TECH_DEBT_PLAN.md 附录（N1/N2 手动验收清单）。
"""
from __future__ import annotations

import importlib
import json

from careercrew_core.tools.browser.boss_search import _looks_blocked, parse_job_cards
from careercrew_core.tools.browser.throttle import gauss_delay_ms
from careercrew_core.tools.internal.search_jobs import make_search_jobs_tool

# tools.internal.__init__ 把 `search_jobs` 名字遮蔽成 tool 对象，
# monkeypatch 字符串路径会解析到遮蔽后的属性——必须显式取 sys.modules 里的模块。
sj_mod = importlib.import_module("careercrew_core.tools.internal.search_jobs")
boss_mod = importlib.import_module("careercrew_core.tools.browser.boss_search")


class FakeEl:
    """ElementHandle 协议桩。"""

    def __init__(self, text: str = "", attrs: dict | None = None,
                 children: list[FakeEl] | None = None, tags: tuple = ()):
        self._text = text
        self._attrs = attrs or {}
        self._children = children or []
        self._tags = set(tags)

    def inner_text(self) -> str:
        return self._text

    def get_attribute(self, name: str) -> str | None:
        return self._attrs.get(name)

    def query_selector(self, sel: str):
        for child in self._children:
            if child.matches(sel):
                return child
        return None

    def query_selector_all(self, sel: str):
        return [c for c in self._children if c.matches(sel)]

    def matches(self, sel: str) -> bool:
        return sel in self._tags


def _card(title="大模型应用工程师", area="北京·朝阳", salary="25-35K",
          company="字节跳动", href="/job_card/abc.html", tags=("3-5年", "本科")):
    return FakeEl(tags=(".job-name", ".job-area", ".salary", ".company-name a", "a.job-card-left", ".filter-labels li"), children=[
        FakeEl(tags=(".job-name",), text=title),
        FakeEl(tags=(".job-area",), text=area),
        FakeEl(tags=(".salary",), text=salary),
        FakeEl(tags=(".company-name a",), text=company),
        FakeEl(tags=("a.job-card-left",), attrs={"href": href}),
        *[FakeEl(tags=(".filter-labels li",), text=t) for t in tags],
    ])


def test_parse_job_cards_full_fields() -> None:
    jobs = parse_job_cards([_card()])
    assert len(jobs) == 1
    j = jobs[0]
    assert j["title"] == "大模型应用工程师"
    assert j["company"] == "字节跳动"
    assert j["city"] == "北京·朝阳"
    assert j["salary"] == "25-35K"
    assert j["experience"] == "3-5年 | 本科"
    assert j["url"].endswith("/job_card/abc.html") and j["url"].startswith("https://www.zhipin.com")
    assert j["source"] == "boss"


def test_parse_job_cards_relative_href_and_dirty_drop() -> None:
    good = _card()
    dirty = FakeEl(tags=(".job-name",))  # 只有空标题 -> 丢弃
    jobs = parse_job_cards([good, dirty])
    assert len(jobs) == 1


def test_gauss_delay_clamped(monkeypatch) -> None:
    monkeypatch.setattr("random.gauss", lambda mu, sigma: -999.0)
    assert gauss_delay_ms() == 300          # 下界 clamp
    monkeypatch.setattr("random.gauss", lambda mu, sigma: 99_999.0)
    assert gauss_delay_ms() == 5000         # 上界 clamp


def test_looks_blocked_on_verification_page() -> None:
    class BlockedPage:
        def locator(self, sel):
            class L:
                def count(self): return 1
            return L()
        def query_selector(self, sel): return None

    assert _looks_blocked(BlockedPage()) is True


class FakeStore:
    """记录调用的 JobsStore 桩：库内永远未命中。"""

    def __init__(self):
        self.upserted = []

    def search(self, direction, top_k=8, max_age_days=7.0):
        return []

    def upsert(self, jobs, direction):
        self.upserted.extend(jobs)


def test_search_jobs_falls_back_to_mcp_when_boss_disabled(monkeypatch) -> None:
    calls = {"boss": 0, "mcp": 0}

    def fail_boss(*a, **k):
        calls["boss"] += 1
        raise AssertionError("Boss 未配置时不应触发")

    monkeypatch.setattr(
        sj_mod, "search_jobs_mcp",
        lambda d, top_k=8: (calls.__setitem__("mcp", calls["mcp"] + 1) or [
            {"title": t, "company": "C", "city": "北京", "salary": "20K",
             "experience": "", "jd": "", "url": "", "source": "liepin"}
            for t in ("Java 工程师",)
        ]),
    )
    tool = make_search_jobs_tool(FakeStore(), boss_cdp_url="")   # Boss 未配置
    out = json.loads(tool.invoke({"direction": "Java", "top_k": 3}))
    assert calls == {"boss": 0, "mcp": 1}
    assert out[0]["title"] == "Java 工程师"


def test_search_jobs_boss_first_then_mcp_fallback(monkeypatch) -> None:
    store = FakeStore()
    mcp_calls = {"n": 0}

    def boss_ok(direction, top_k=8, cdp_url="", city="", pause=True):
        return [{"title": f"Boss岗{i}", "company": "B", "city": "上海", "salary": "30K",
                 "experience": "", "jd": "", "url": f"https://www.zhipin.com/job{i}",
                 "source": "boss"} for i in range(top_k)]

    def mcp_fail(direction, top_k=8):
        mcp_calls["n"] += 1
        raise RuntimeError("mcp down")

    monkeypatch.setattr(boss_mod, "search_boss_jobs", boss_ok)
    monkeypatch.setattr(sj_mod, "search_jobs_mcp", mcp_fail)

    tool = make_search_jobs_tool(store, boss_cdp_url="http://127.0.0.1:9222")
    out = json.loads(tool.invoke({"direction": "大模型应用", "top_k": 2}))
    assert len(out) == 2 and out[0]["title"] == "Boss岗0"
    assert mcp_calls["n"] == 0                       # Boss 成功即不降级
    assert [j["title"] for j in store.upserted] == ["Boss岗0", "Boss岗1"]  # 结果入库


def test_search_jobs_boss_failure_degrades_to_mcp(monkeypatch) -> None:
    def boss_fail(*a, **k):
        raise RuntimeError("安全验证")

    monkeypatch.setattr(boss_mod, "search_boss_jobs", boss_fail)
    monkeypatch.setattr(
        sj_mod, "search_jobs_mcp",
        lambda d, top_k=8: [{"title": "猎聘岗", "company": "L", "city": "深圳", "salary": "18K",
                             "experience": "", "jd": "", "url": "", "source": "liepin"}],
    )
    tool = make_search_jobs_tool(None, boss_cdp_url="http://127.0.0.1:9222")
    out = json.loads(tool.invoke({"direction": "数据分析"}))
    assert out[0]["title"] == "猎聘岗"
