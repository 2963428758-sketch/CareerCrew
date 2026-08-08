"""read_image 工具：用视觉模型（硅基流动 GLM-4.5V）读取图片内容（简历截图/作品集）。

关键设计：视觉模型（Qwen3-VL/GLM-4.5V）不兼容 function calling，故视觉做成工具供
agent 按需调（ReAct 主 LLM 保持 tool-calling 文本模型）。vision_caller 注入便于测试。
"""
from __future__ import annotations

import base64
from pathlib import Path

from langchain_core.tools import BaseTool, tool

# 视觉模型默认（硅基流动）；可换 Qwen3-VL 系列
DEFAULT_VISION_MODEL = "GLM-4.5V"


def make_read_image_tool(settings, vision_caller=None, model: str = DEFAULT_VISION_MODEL) -> BaseTool:
    """构造 read_image 工具。vision_caller(image_b64, prompt) -> str。"""

    def _default_call(image_b64: str, prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(base_url=settings.llm.base_url, api_key=settings.llm.api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }],
            max_tokens=512,
        )
        return resp.choices[0].message.content or ""

    caller = vision_caller or _default_call

    @tool
    def read_image(image_path: str, prompt: str = "请描述图片内容并提取其中的文字。") -> str:
        """读取图片内容（简历截图 / 作品集 / 笔试截图），返回描述与提取的文字。

        Args:
            image_path: 本地图片路径。
            prompt: 读取指令（默认描述 + 提取文字）。
        """
        p = Path(image_path)
        if not p.exists():
            return f"[error] 图片不存在: {image_path}"
        try:
            b64 = base64.b64encode(p.read_bytes()).decode()
            return caller(b64, prompt)
        except Exception as e:
            return f"[error] {type(e).__name__}: {e}"

    return read_image
