"""sse.friendly_error 错误信息收敛测试。

未知类别的异常不得透传原始文本（可能含内部路径/供应商端点），
改给通用提示 + 追踪号；已知类别同样不得暴露底层细节。
"""
from __future__ import annotations

from careercrew_api.sse import _clip_detail, friendly_error


def test_cjk_business_error_passthrough():
    class ChineseError(Exception):
        pass

    assert friendly_error(ChineseError("简历解析失败：文件损坏")) == "简历解析失败：文件损坏"


def test_unknown_exception_does_not_leak_raw_text():
    class OpaqueError(Exception):
        pass

    exc = OpaqueError("/srv/secret/path internal endpoint https://provider.example/v1 boom")
    out = friendly_error(exc)
    assert "/srv/secret/path" not in out
    assert "生成失败" in out


def test_known_category_does_not_leak_provider_detail():
    exc = ConnectionError("connection refused to api.siliconflow.cn")
    out = friendly_error(exc)
    assert "无法连接 AI 服务" in out
    assert "api.siliconflow.cn" not in out


def test_long_detail_is_clipped_to_single_line():
    raw = "x" * 500 + "\n" + "y" * 500
    clipped = _clip_detail(raw)
    assert len(clipped) <= 201  # 上限 + 省略号
    assert clipped.endswith("…")
    assert "\n" not in clipped


def test_timeout_and_quota_categories():
    assert "超时" in friendly_error(TimeoutError("request timed out after 60s"))
    assert "繁忙" in friendly_error(RuntimeError("429 Too Many Requests"))
    assert "暂时不可用" in friendly_error(RuntimeError("401 Unauthorized"))


def test_trace_id_included_when_available(monkeypatch):
    from careercrew_api.logging_config import request_id_var

    token = request_id_var.set("req-abc-123")
    try:
        out = friendly_error(ValueError("opaque"))
        assert "追踪号 req-abc-123" in out
    finally:
        request_id_var.reset(token)
