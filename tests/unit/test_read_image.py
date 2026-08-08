"""read_image 工具测试（多模态）。"""
from __future__ import annotations

import base64
import os

import pytest
from dotenv import load_dotenv

from careercrew_core.tools.internal.read_image import make_read_image_tool

load_dotenv()

# 1x1 透明 PNG
PNG_1x1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def test_read_image_with_fake_caller(tmp_path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(base64.b64decode(PNG_1x1))
    calls = []

    def fake_caller(b64: str, prompt: str) -> str:
        calls.append((b64, prompt))
        return "这是一张简历截图，含 Python 技能"

    t = make_read_image_tool(None, vision_caller=fake_caller)
    out = t.invoke({"image_path": str(img)})
    assert "简历截图" in out
    assert len(calls) == 1
    assert calls[0][0] == base64.b64encode(img.read_bytes()).decode()
    assert "描述" in calls[0][1]


def test_read_image_missing_file(tmp_path) -> None:
    t = make_read_image_tool(None, vision_caller=lambda b, p: "x")
    out = t.invoke({"image_path": str(tmp_path / "nope.png")})
    assert "error" in out


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("SILICONFLOW_API_KEY"), reason="需 SILICONFLOW_API_KEY")
def test_read_image_real(tmp_path) -> None:
    """真实 GLM-4.5V 视觉 API（硅基流动）。"""
    from careercrew_core.state.settings import load_settings

    img = tmp_path / "x.png"
    img.write_bytes(base64.b64decode(PNG_1x1))
    t = make_read_image_tool(load_settings())
    out = t.invoke({"image_path": str(img)})
    assert isinstance(out, str) and len(out) > 0
