"""配置加载与校验（A3）。

读取 config/settings.yaml -> 递归替换 ${VAR} 环境变量 -> pydantic 嵌套模型校验
-> 语义校验（api_key / backend 取值）。缺关键字段或语义非法时 fail-fast，
错误信息含字段路径（如 vector_store.backend），不吞异常。

设计：
- 不做网络/IO，只读配置文件 + 环境变量；首次调用探活留到 A4（create_llm）。
- ${VAR} 占位用正则递归替换，仅作用于字符串值，保留其他类型。
- pydantic v2 嵌套模型：ValidationError 的 loc 即字段路径，格式化为可读错误。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

# ── 默认配置路径：careercrew_core/state/settings.py -> parents[2] = 项目根 ──
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"

# ${VAR} 环境变量占位（仅 A-Za-z_ 开头的标识符）
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# 向量库后端合法取值
_VALID_VECTOR_BACKENDS = {"milvus_lite", "milvus_docker", "chroma"}
_VALID_LOADER_BACKENDS = {"markitdown", "pymupdf", "python-docx"}


class SettingsError(Exception):
    """配置加载或校验失败（fail-fast）。"""


# ── 嵌套模型：镜像 config/settings.yaml 结构 ──


class LLMSettings(BaseModel):
    provider: str
    model: str
    base_url: str
    api_key: str
    temperature: float = 0.3
    max_tokens: int = 2048


class EmbeddingSettings(BaseModel):
    provider: str
    model: str
    model_path: str
    use_fp16: bool = False
    batch_size: int = 12


class RerankSettings(BaseModel):
    backend: str  # none | siliconflow | local_bge
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    top_m: int = 30


class VectorStoreSettings(BaseModel):
    backend: str
    persist_path: str
    collections: dict[str, str]


class RetrievalSettings(BaseModel):
    mode: str
    fusion_algorithm: str
    top_k_dense: int
    top_k_sparse: int
    top_k_final: int


class ChunkingSettings(BaseModel):
    strategy: str
    chunk_size: int
    chunk_overlap: int
    contextual: bool


class LoadersSettings(BaseModel):
    """文档加载器配置（D4 落地，与 DEV_SPEC §5.5 对齐）。"""

    backend: str = "markitdown"  # markitdown | pymupdf | python-docx（per-format 回退）


class RagSettings(BaseModel):
    retrieval: RetrievalSettings
    chunking: ChunkingSettings
    loaders: LoadersSettings = LoadersSettings()


class CheckpointerSettings(BaseModel):
    backend: str
    path: str


class SupervisorSettings(BaseModel):
    checkpointer: CheckpointerSettings
    max_consecutive_agent_turns: int = 10


class EpisodicSettings(BaseModel):
    transcript_dir: str
    vectorize: bool


class UserModelSettings(BaseModel):
    path: str


class CompactionSettings(BaseModel):
    enabled: bool
    token_threshold_ratio: float
    retention_tokens: int


class MemorySettings(BaseModel):
    episodic: EpisodicSettings
    user_model: UserModelSettings
    compaction: CompactionSettings


class RegistrySettings(BaseModel):
    internal: list[str]
    mcp: list[str]


class ToolsHitlSettings(BaseModel):
    requires_confirmation: list[str]


class ToolsSettings(BaseModel):
    registry: RegistrySettings
    hitl: ToolsHitlSettings


class HitlSettings(BaseModel):
    default_policy: str  # confirm | auto


class ObservabilitySettings(BaseModel):
    enabled: bool
    log_file: str


class DashboardSettings(BaseModel):
    enabled: bool
    port: int
    traces_dir: str


class Settings(BaseModel):
    """顶层配置，结构与 config/settings.yaml 一一对应。"""

    llm: LLMSettings
    embedding: EmbeddingSettings
    rerank: RerankSettings
    vector_store: VectorStoreSettings
    rag: RagSettings
    supervisor: SupervisorSettings
    memory: MemorySettings
    tools: ToolsSettings
    hitl: HitlSettings
    observability: ObservabilitySettings
    dashboard: DashboardSettings


# ── 环境变量替换 ──


def _substitute_env(value: Any) -> Any:
    """递归替换字符串值中的 ${VAR} 为 os.environ[VAR]（未设置则替换为空串）。"""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env(v) for v in value]
    return value


def _format_validation_errors(err: ValidationError) -> str:
    lines = ["配置校验失败（字段缺失或类型错误）:"]
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"])
        lines.append(f"  - {loc}: {e['msg']}")
    return "\n".join(lines)


def validate_settings(settings: Settings) -> None:
    """语义校验（构造后的跨字段约束），失败抛 SettingsError。

    与 pydantic 字段级校验互补：这里查「字段值合法但语义不对」的情况，
    如 api_key 未设置、backend 取值非法。
    """
    problems: list[str] = []

    # LLM api_key：空或未解析的 ${VAR} 视为未设置
    if not settings.llm.api_key or "${" in settings.llm.api_key:
        problems.append("llm.api_key 未设置（检查环境变量 SILICONFLOW_API_KEY）")

    # Rerank api_key：仅 backend=siliconflow 时要求
    if settings.rerank.backend == "siliconflow" and (
        not settings.rerank.api_key or "${" in settings.rerank.api_key
    ):
        problems.append("rerank.api_key 未设置（backend=siliconflow 时需 SILICONFLOW_API_KEY）")

    # 向量库后端取值
    if settings.vector_store.backend not in _VALID_VECTOR_BACKENDS:
        problems.append(
            f"vector_store.backend 取值非法: {settings.vector_store.backend}，"
            f"应为 {sorted(_VALID_VECTOR_BACKENDS)} 之一"
        )

    # 文档加载器后端取值
    if settings.rag.loaders.backend not in _VALID_LOADER_BACKENDS:
        problems.append(
            f"rag.loaders.backend 取值非法: {settings.rag.loaders.backend}，"
            f"应为 {sorted(_VALID_LOADER_BACKENDS)} 之一"
        )

    if problems:
        raise SettingsError("配置语义校验失败:\n" + "\n".join(f"  - {p}" for p in problems))


def load_settings(path: str | Path | None = None) -> Settings:
    """加载并校验配置。fail-fast：文件缺失 / 字段缺失 / 语义非法均抛 SettingsError。"""
    load_dotenv()  # 读取 .env（已 gitignore），注入 SILICONFLOW_API_KEY 等
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise SettingsError(f"配置文件不存在: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SettingsError(f"配置文件顶层应为映射，实际: {type(raw).__name__}")

    data = _substitute_env(raw)

    try:
        settings = Settings.model_validate(data)
    except ValidationError as err:
        raise SettingsError(_format_validation_errors(err)) from None

    validate_settings(settings)
    return settings
