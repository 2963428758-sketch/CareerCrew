"""FastAPI 依赖注入（测试用 dependency_overrides 换 FakeRuntime）。"""
from __future__ import annotations

from careercrew_api.runtime import CareerCrewRuntime, get_runtime


def get_runtime_dep() -> CareerCrewRuntime:
    """FastAPI 依赖：返回运行时单例。测试用 app.dependency_overrides 换 fake。"""
    return get_runtime()
