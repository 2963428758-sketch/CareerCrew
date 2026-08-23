"""profile_update 工具：结构化更新语义事实（Schema 约束替代白名单路径校验）。

工厂注入 SemanticFactStore + 默认 user_id。字段 key 用点路径，白名单校验
保留；写语义事实时带来源（agent 名）与置信度。
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from careercrew_core.memory.semantic import SemanticFactStore


def make_profile_update_tool(store: SemanticFactStore, user_id: str, source: str = "agent",
                             memory_service=None) -> BaseTool:
    """构造 profile_update 工具（注入 SemanticFactStore + 默认 user_id + 来源）。"""

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
            model = (
                memory_service.update_profile(user_id, fields, source=source)
                if memory_service is not None
                else store.update(user_id, fields, source=source)
            )
            return f"User Model 更新成功: {model.model_dump_json()}"
        except (PermissionError, ValueError) as e:
            return f"[error] {e}"

    return profile_update
