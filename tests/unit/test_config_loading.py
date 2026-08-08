"""A3 配置加载与校验测试。

测试即文档：描述 load_settings 的契约 —— 完整配置可加载；缺关键字段时抛 SettingsError
且信息含字段路径；${VAR} 占位被递归替换；api_key 未设置 / backend 取值非法时 fail-fast。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from careercrew_core.state.settings import (
    Settings,
    SettingsError,
    load_settings,
    validate_settings,
)


def _write_config(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "settings.yaml"
    p.write_text(yaml_safe_dump(data), encoding="utf-8")
    return p


def yaml_safe_dump(data: dict) -> str:
    import yaml

    return yaml.safe_dump(data, allow_unicode=True)


def test_load_settings_ok(tmp_path: Path, valid_config_data: dict) -> None:
    settings = load_settings(_write_config(tmp_path, valid_config_data))
    assert isinstance(settings, Settings)
    assert settings.llm.model == "deepseek-ai/DeepSeek-V4-Flash"
    assert settings.vector_store.backend == "milvus_lite"
    assert settings.vector_store.collections["knowledge"] == "careercrew_kb"
    assert settings.rag.retrieval.mode == "hybrid"
    assert settings.rag.chunking.contextual is True
    assert settings.rag.loaders.backend == "markitdown"
    assert settings.tools.hitl.requires_confirmation == ["submit_application", "accept_offer"]


def test_missing_field_raises_with_path(tmp_path: Path, valid_config_data: dict) -> None:
    del valid_config_data["vector_store"]["backend"]
    with pytest.raises(SettingsError) as exc:
        load_settings(_write_config(tmp_path, valid_config_data))
    msg = str(exc.value)
    assert "vector_store" in msg
    assert "backend" in msg


def test_env_var_substitution(tmp_path: Path, valid_config_data: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    valid_config_data["llm"]["api_key"] = "${TEST_SF_KEY}"
    valid_config_data["rerank"]["api_key"] = "${TEST_SF_KEY}"
    monkeypatch.setenv("TEST_SF_KEY", "sk-from-env")
    settings = load_settings(_write_config(tmp_path, valid_config_data))
    assert settings.llm.api_key == "sk-from-env"
    assert settings.rerank.api_key == "sk-from-env"


def test_missing_api_key_fail_fast(tmp_path: Path, valid_config_data: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    valid_config_data["llm"]["api_key"] = "${DEFINITELY_UNSET_VAR}"
    valid_config_data["rerank"]["api_key"] = "${DEFINITELY_UNSET_VAR}"
    monkeypatch.delenv("DEFINITELY_UNSET_VAR", raising=False)
    with pytest.raises(SettingsError) as exc:
        load_settings(_write_config(tmp_path, valid_config_data))
    assert "api_key" in str(exc.value)


def test_invalid_vector_store_backend(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["vector_store"]["backend"] = "weird_db"
    with pytest.raises(SettingsError) as exc:
        load_settings(_write_config(tmp_path, valid_config_data))
    assert "vector_store.backend" in str(exc.value)


def test_missing_config_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SettingsError) as exc:
        load_settings(tmp_path / "nope.yaml")
    assert "不存在" in str(exc.value)


def test_validate_settings_standalone(valid_config_data: dict) -> None:
    settings = Settings.model_validate(valid_config_data)
    validate_settings(settings)  # 不抛即通过


def test_rerank_none_backend_skips_api_key(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["rerank"]["backend"] = "none"
    valid_config_data["rerank"]["api_key"] = ""
    settings = load_settings(_write_config(tmp_path, valid_config_data))
    assert settings.rerank.backend == "none"


def test_relative_paths_resolved_to_project_root() -> None:
    """相对路径字段解析为基于项目根的绝对路径（任意 CWD 都能跑）。"""
    import os

    from careercrew_core.state.settings import PROJECT_ROOT

    settings = load_settings()  # 读 config/settings.yaml（相对路径）
    assert os.path.isabs(settings.embedding.model_path)
    assert settings.embedding.model_path == str(
        PROJECT_ROOT / "data/ms_cache/models/BAAI--bge-m3/snapshots/master"
    )
    assert os.path.isabs(settings.vector_store.persist_path)
    assert os.path.isabs(settings.supervisor.checkpointer.path)

def test_invalid_loader_backend(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["rag"]["loaders"] = {"backend": "weird"}
    with pytest.raises(SettingsError) as exc:
        load_settings(_write_config(tmp_path, valid_config_data))
    assert "rag.loaders.backend" in str(exc.value)
