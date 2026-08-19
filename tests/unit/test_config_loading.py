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
    assert settings.llm.model == "zai-org/GLM-4.5V"
    assert settings.vector_store.backend == "qdrant"
    assert settings.vector_store.collections["knowledge"] == "careercrew_mm"
    assert settings.rag.retrieval.mode == "hybrid"
    assert settings.rag.chunking.contextual is True
    assert settings.rag.loaders.backend == "mineru"
    assert settings.rag.loaders.provider == "local"  # 单测 fixture 走本地路由，不依赖云端 key
    assert settings.vlm.model == "zai-org/GLM-4.5V"
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


def test_old_vector_backend_migration_hint(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["vector_store"]["backend"] = "milvus_lite"
    with pytest.raises(SettingsError) as exc:
        load_settings(_write_config(tmp_path, valid_config_data))
    msg = str(exc.value)
    assert "vector_store.backend" in msg
    assert "请改为 qdrant" in msg


def test_old_loader_backend_migration_hint(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["rag"]["loaders"] = {"backend": "markitdown"}
    with pytest.raises(SettingsError) as exc:
        load_settings(_write_config(tmp_path, valid_config_data))
    assert "rag.loaders.backend" in str(exc.value)
    assert "请改为 mineru" in str(exc.value)


def test_vlm_api_key_missing_fail_fast(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["vlm"]["api_key"] = "${DEFINITELY_UNSET_VAR}"
    with pytest.raises(SettingsError) as exc:
        load_settings(_write_config(tmp_path, valid_config_data))
    assert "vlm.api_key" in str(exc.value)


def test_rerank_none_backend_skips_api_key(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["rerank"]["backend"] = "none"
    valid_config_data["rerank"]["api_key"] = ""
    settings = load_settings(_write_config(tmp_path, valid_config_data))
    assert settings.rerank.backend == "none"


def test_relative_paths_resolved_to_project_root(tmp_path: Path, valid_config_data: dict) -> None:
    """相对路径字段解析为基于项目根的绝对路径（任意 CWD 都能跑）。

    用 fixture 配置（不依赖仓库 config/settings.yaml 与本机环境变量），
    保证在 CI（无 .env / 无 MinerU、LangSmith key）也能通过。
    """
    import os

    from careercrew_core.state.settings import PROJECT_ROOT

    valid_config_data["embedding"]["model_path"] = "./models/bge"
    valid_config_data["rag"]["loaders"]["output_dir"] = "./data/parsed"
    settings = load_settings(_write_config(tmp_path, valid_config_data))
    assert os.path.isabs(settings.embedding.model_path)
    assert settings.embedding.model_path == str(PROJECT_ROOT / "models" / "bge")
    assert settings.rag.loaders.output_dir == str(PROJECT_ROOT / "data" / "parsed")

def test_invalid_loader_backend(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["rag"]["loaders"] = {"backend": "weird"}
    with pytest.raises(SettingsError) as exc:
        load_settings(_write_config(tmp_path, valid_config_data))
    assert "rag.loaders.backend" in str(exc.value)


def test_loader_provider_api_requires_key(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["rag"]["loaders"]["provider"] = "api"
    valid_config_data["rag"]["loaders"]["api_key"] = ""
    with pytest.raises(SettingsError) as exc:
        load_settings(_write_config(tmp_path, valid_config_data))
    assert "rag.loaders.api_key" in str(exc.value)


def test_loader_provider_api_key_from_env(tmp_path: Path, valid_config_data: dict, monkeypatch) -> None:
    valid_config_data["rag"]["loaders"]["provider"] = "api"
    valid_config_data["rag"]["loaders"]["api_key"] = "${TEST_MINERU_KEY}"
    monkeypatch.setenv("TEST_MINERU_KEY", "sk-mineru")
    settings = load_settings(_write_config(tmp_path, valid_config_data))
    assert settings.rag.loaders.api_key == "sk-mineru"


def test_invalid_loader_provider(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["rag"]["loaders"]["provider"] = "weird"
    with pytest.raises(SettingsError) as exc:
        load_settings(_write_config(tmp_path, valid_config_data))
    assert "rag.loaders.provider" in str(exc.value)


def test_invalid_loader_model_version(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["rag"]["loaders"]["model_version"] = "weird"
    with pytest.raises(SettingsError) as exc:
        load_settings(_write_config(tmp_path, valid_config_data))
    assert "rag.loaders.model_version" in str(exc.value)


def test_auth_backend_postgres_falls_back_to_database_url(tmp_path, monkeypatch):
    from careercrew_core.state import settings as settings_module
    from careercrew_core.state.settings import SettingsError

    config = tmp_path / "settings.yaml"
    config.write_text(
        "auth:\n  database_url: ''\n", encoding="utf-8"
    )
    monkeypatch.setattr(settings_module, "DEFAULT_CONFIG_PATH", config)
    monkeypatch.setattr(settings_module, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://careercrew:careercrew@localhost:5432/careercrew")
    auth = settings_module.load_auth_settings()
    assert auth.database_url == "postgresql://careercrew:careercrew@localhost:5432/careercrew"


def test_auth_backend_postgres_without_dsn_fails(tmp_path, monkeypatch):
    from careercrew_core.state import settings as settings_module
    from careercrew_core.state.settings import SettingsError

    config = tmp_path / "settings.yaml"
    config.write_text(
        "auth:\n  database_url: ''\n", encoding="utf-8"
    )
    monkeypatch.setattr(settings_module, "DEFAULT_CONFIG_PATH", config)
    monkeypatch.setattr(settings_module, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AUTH_DATABASE_URL", raising=False)
    with pytest.raises(SettingsError, match="AUTH_DATABASE_URL"):
        settings_module.load_auth_settings()
