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
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"

# ${VAR} 环境变量占位（仅 A-Za-z_ 开头的标识符）
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# 向量库后端合法取值（多模态 RAG 全面替换后仅剩 Qdrant）
_VALID_VECTOR_BACKENDS = {"qdrant"}
_VALID_LOADER_BACKENDS = {"mineru"}
_VALID_LOADER_PROVIDERS = {"api", "local"}
_VALID_LOADER_MODEL_VERSIONS = {"pipeline", "vlm", "MinerU-HTML"}

# 旧值 -> 迁移指引（fail-fast 时提示，不静默替换）
_VECTOR_BACKEND_MIGRATION = {
    "milvus_lite": "qdrant",
    "milvus_docker": "qdrant",
    "chroma": "qdrant",
}
_LOADER_BACKEND_MIGRATION = {
    "markitdown": "mineru",
    "pymupdf": "mineru",
    "python-docx": "mineru",
}


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
    url: str = "http://localhost:6333"
    api_key: str = ""
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
    """文档加载器配置（多模态 RAG：MinerU 云端 API 或本地子进程解析）。"""

    backend: str = "mineru"
    provider: str = "api"  # api（云端精准解析，推荐，本机零推理负载）| local（本地子进程）
    api_key: str = ""  # provider=api 时必填（MINERU_API_KEY）
    model_version: str = "vlm"  # pipeline | vlm（推荐）| MinerU-HTML
    poll_interval: int = 5  # API 轮询间隔（秒）
    timeout: int = 1800  # API 任务最长等待（秒）
    output_dir: str = "./data/parsed"  # MinerU 产物落盘（页面图/对象裁剪图/Markdown）
    device: str = "cpu"  # MinerU 子进程推理设备（cpu/cuda/mps；8GB 显存机型固定 cpu）
    method: str = "auto"  # 解析方法：auto | txt（纯文本 PDF 最快，跳过 OCR）| ocr（强制 OCR）
    formula: bool = True  # 公式识别（最重的模型之一；课件/简历等无公式文档可关掉提速）
    table: bool = True  # 表格识别
    language: str = "ch"  # 文档语言（API 参数，默认 ch）


class RagSettings(BaseModel):
    retrieval: RetrievalSettings
    chunking: ChunkingSettings
    loaders: LoadersSettings = LoadersSettings()


class VLMSettings(BaseModel):
    """多模态生成/精排（硅基流动 API）。"""

    model: str
    rerank_model: str
    base_url: str = "https://api.siliconflow.cn/v1"
    api_key: str = ""


class CheckpointerSettings(BaseModel):
    backend: str
    path: str
    url: str = ""  # postgres 后端用（DATABASE_URL）；sqlite/memory 忽略


class SupervisorSettings(BaseModel):
    checkpointer: CheckpointerSettings
    max_consecutive_agent_turns: int = 10


class PostgresSettings(BaseModel):
    """Postgres 记忆库连接（生产唯一持久化后端）。"""

    dsn: str = ""


class EpisodicSettings(BaseModel):
    collection: str = "careercrew_episodic_v2"  # Qdrant 情景记忆 collection
    vectorize: bool


class CompactionSettings(BaseModel):
    enabled: bool
    token_threshold_ratio: float
    retention_tokens: int


class MemoryRouterSettings(BaseModel):
    """LLM 路由检索配置（Claude Code 式：从事实清单选 top-N，非向量）。"""

    top_n: int = 5
    max_inject_tokens: int = 2000  # 自动注入总 token 预算


class ConsolidationSettings(BaseModel):
    """后台 consolidation 门控（Auto Dream 式）。"""

    min_interval_hours: int = 24
    min_sessions: int = 5


class MemorySettings(BaseModel):
    """记忆子系统配置。enabled=false 时记忆默认关闭（Codex 式治理）。"""

    enabled: bool = False
    postgres: PostgresSettings = PostgresSettings()
    episodic: EpisodicSettings
    compaction: CompactionSettings
    router: MemoryRouterSettings = MemoryRouterSettings()
    consolidation: ConsolidationSettings = ConsolidationSettings()


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


class LangSmithSettings(BaseModel):
    """LangSmith 追踪（AGENT_LANGSMITH_SPEC Part B）。"""

    enabled: bool
    project: str = "careercrew"
    api_key: str = ""
    masking: bool = True
    max_chars: int = 2000


class Settings(BaseModel):
    """顶层配置，结构与 config/settings.yaml 一一对应。"""

    llm: LLMSettings
    embedding: EmbeddingSettings
    rerank: RerankSettings
    vector_store: VectorStoreSettings
    rag: RagSettings
    vlm: VLMSettings
    supervisor: SupervisorSettings
    memory: MemorySettings
    tools: ToolsSettings
    hitl: HitlSettings
    langsmith: LangSmithSettings


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


def _resolve_path(value: str | None) -> str | None:
    """相对路径解析为基于项目根的绝对路径（否则按 CWD 解析，换目录跑就挂）。"""
    if not value:
        return value
    p = Path(value)
    if p.is_absolute():
        return str(p)
    return str(PROJECT_ROOT / p)


def _resolve_paths(settings: Settings) -> Settings:
    """把所有相对路径字段解析为基于项目根的绝对路径。"""
    settings.embedding.model_path = _resolve_path(settings.embedding.model_path)
    settings.rag.loaders.output_dir = _resolve_path(settings.rag.loaders.output_dir)
    settings.supervisor.checkpointer.path = _resolve_path(settings.supervisor.checkpointer.path)
    return settings


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

    # VLM api_key（多模态生成/精排）
    if not settings.vlm.api_key or "${" in settings.vlm.api_key:
        problems.append("vlm.api_key 未设置（需 SILICONFLOW_API_KEY）")

    # LangSmith api_key：enabled=true 时必须提供 LANGSMITH_API_KEY
    if settings.langsmith.enabled and (
        not settings.langsmith.api_key or "${" in settings.langsmith.api_key
    ):
        problems.append("langsmith.api_key 未设置（enabled=true 时需 LANGSMITH_API_KEY）")

    # 向量库后端取值
    if settings.vector_store.backend not in _VALID_VECTOR_BACKENDS:
        hint = _VECTOR_BACKEND_MIGRATION.get(settings.vector_store.backend)
        migration = f"，已迁移，请改为 {hint}" if hint else ""
        problems.append(
            f"vector_store.backend 取值非法: {settings.vector_store.backend}，"
            f"应为 {sorted(_VALID_VECTOR_BACKENDS)} 之一{migration}"
        )

    # 文档加载器后端取值
    if settings.rag.loaders.backend not in _VALID_LOADER_BACKENDS:
        hint = _LOADER_BACKEND_MIGRATION.get(settings.rag.loaders.backend)
        migration = f"，已迁移，请改为 {hint}" if hint else ""
        problems.append(
            f"rag.loaders.backend 取值非法: {settings.rag.loaders.backend}，"
            f"应为 {sorted(_VALID_LOADER_BACKENDS)} 之一{migration}"
        )

    # 文档加载器 provider 取值
    if settings.rag.loaders.provider not in _VALID_LOADER_PROVIDERS:
        problems.append(
            f"rag.loaders.provider 取值非法: {settings.rag.loaders.provider}，"
            f"应为 {sorted(_VALID_LOADER_PROVIDERS)} 之一"
        )

    # provider=api 时必须提供 MinerU API key
    if settings.rag.loaders.provider == "api" and (
        not settings.rag.loaders.api_key or "${" in settings.rag.loaders.api_key
    ):
        problems.append("rag.loaders.api_key 未设置（provider=api 时需 MINERU_API_KEY）")

    # model_version 取值
    if settings.rag.loaders.model_version not in _VALID_LOADER_MODEL_VERSIONS:
        problems.append(
            f"rag.loaders.model_version 取值非法: {settings.rag.loaders.model_version}，"
            f"应为 {sorted(_VALID_LOADER_MODEL_VERSIONS)} 之一"
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
    return _resolve_paths(settings)
