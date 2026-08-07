"""profile_update 工具（C5）：结构化更新 User Model，字段约束。

工厂注入 store + 默认 user_id（避免硬编码 load_settings，单测可传 tmp store）。
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from careercrew_core.memory.user_model import UserModelStore


def make_profile_update_tool(store: UserModelStore, user_id: str = "u_001") -> BaseTool:
    """构造 profile_update 工具（注入 store + 默认 user_id）。"""

    @tool
    def profile_update(fields: dict) -> str:
        """更新用户画像 / 偏好 / 目标公司池（结构化字段，非法字段拒绝）。

        Args:
            fields: 要更新的字段，key 用点路径。允许：
                profile.skills / profile.level / profile.direction / profile.experience_years
                target_companies
                preferences.salary_min / preferences.salary_max / preferences.city / preferences.work_mode
                例：{"profile.skills": ["Python","RAG"], "target_companies": ["字节"]}
        """
        try:
            model = store.update(user_id, fields)
            return f"User Model 更新成功: {model.model_dump_json()}"
        except ValueError as e:
            return f"[error] {e}"

    return profile_update
