# CareerCrew 后端镜像（多阶段：builder 把重依赖装进独立 venv，runtime 只携带产物）
# 构建上下文即仓库根：docker build -t careercrew .
#
# 分层策略：占位包 + pyproject 先装全部依赖——该层仅随 pyproject.toml 变化失效，
# 业务代码改动不再触发 torch/FlagEmbedding 等重依赖的全量重装。

# ── 阶段一：依赖构建 ──
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app

# 先单独装 CPU 版 torch（FlagEmbedding/sentence-transformers 的依赖），
# 避免后续 pip 解析时拉取 CUDA 版（多出 ~4GB nvidia 运行库）
COPY pyproject.toml README.md ./
RUN mkdir -p careercrew_core careercrew_ai careercrew_api careercrew_mcp \
    && for p in careercrew_core careercrew_ai careercrew_api careercrew_mcp; do \
         echo '"""placeholder for dependency caching"""' > $p/__init__.py; done \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install ".[web]"

# 真实源码覆盖占位包；项目本体以 --no-deps 安装（依赖已就位，秒级），
# 保证非 /app 工作目录启动（如 alembic、scripts）也能导入正确代码
COPY careercrew_core/ careercrew_core/
COPY careercrew_ai/ careercrew_ai/
COPY careercrew_api/ careercrew_api/
COPY careercrew_mcp/ careercrew_mcp/
COPY alembic.ini ./
RUN pip install --no-deps .

# ── 阶段二：运行时 ──
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# healthcheck 用 curl；psycopg/argon2 等带二进制轮子无需编译工具链
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

COPY alembic.ini README.md pyproject.toml ./
COPY migrations/ migrations/
COPY config/ config/
COPY scripts/ scripts/
COPY careercrew_core/ careercrew_core/
COPY careercrew_ai/ careercrew_ai/
COPY careercrew_api/ careercrew_api/
COPY careercrew_mcp/ careercrew_mcp/

# 非 root 运行；data/（上传与解析产物）以 volume 挂载时注意属主
RUN useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 裸 docker run 也有健康检查（compose 的 healthcheck 与此等价）
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

# Alembic baseline 先行（#8 约定），失败即退出不做半启动
CMD ["sh", "-c", "alembic upgrade head && uvicorn careercrew_api.main:app --host 0.0.0.0 --port 8000"]
