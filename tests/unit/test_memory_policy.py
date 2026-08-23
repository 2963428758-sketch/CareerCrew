"""记忆治理策略（全局 + 用户级 + 生效值）测试。"""
from __future__ import annotations

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.policy import MemoryPolicyStore


def test_defaults_off() -> None:
    p = MemoryPolicyStore(FakeMemoryDb())
    assert p.global_policy().enabled is False
    assert p.user_policy("u1").enabled is False
    assert p.user_policy("u1").generate is True


def test_effective_requires_all_layers() -> None:
    p = MemoryPolicyStore(FakeMemoryDb())
    # 特性关 -> 全关
    assert p.effective("u1", feature_enabled=False).enabled is False
    # 全局开、用户开 -> 生效
    p.set_global(enabled=True)
    p.set_user("u1", enabled=True)
    eff = p.effective("u1", feature_enabled=True)
    assert eff.enabled is True
    assert eff.generate is True and eff.use is True
    # 用户 use 关 -> 生效 use 关
    p.set_user("u1", use=False)
    eff2 = p.effective("u1", feature_enabled=True)
    assert eff2.use is False


def test_user_master_switch_disables_generate_and_use() -> None:
    """用户总开关关闭时，子策略即使保留为开也不能实际生效。"""
    p = MemoryPolicyStore(FakeMemoryDb())
    p.set_global(enabled=True, generate=True, use=True)
    p.set_user("u1", enabled=False, generate=True, use=True)

    eff = p.effective("u1", feature_enabled=True)

    assert eff.enabled is False
    assert eff.generate is False
    assert eff.use is False


def test_partial_update_preserves_other_fields() -> None:
    p = MemoryPolicyStore(FakeMemoryDb())
    p.set_user("u1", enabled=True)
    p.set_user("u1", use=False)
    u = p.user_policy("u1")
    assert u.enabled is True
    assert u.generate is True
    assert u.use is False


def test_user_isolation() -> None:
    p = MemoryPolicyStore(FakeMemoryDb())
    p.set_user("u1", enabled=True)
    assert p.user_policy("u2").enabled is False
