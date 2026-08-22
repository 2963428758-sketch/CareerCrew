# CareerCrew 后端镜像（python 3.12 + CPU torch，镜像 ~1.5GB）
# 构建上下文即仓库根：docker build -t careercrew .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# healthcheck 用 curl；psycopg/argon2 等带二进制轮子无需编译工具链
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 先单独装 CPU 版 torch（FlagEmbedding/sentence-transformers 的依赖），
# 避免后续 pip 解析时拉取 CUDA 版（多出 ~4GB nvidia 运行库）
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml README.md ./
COPY careercrew_core/ careercrew_core/
COPY careercrew_ai/ careercrew_ai/
COPY careercrew_api/ careercrew_api/
COPY careercrew_mcp/ careercrew_mcp/
COPY alembic.ini ./
COPY migrations/ migrations/
COPY config/ config/
COPY scripts/ scripts/

RUN pip install ".[web]"

# 非 root 运行；data/（上传与解析产物）以 volume 挂载时注意属主
RUN useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Alembic baseline 先行（#8 约定），失败即退出不做半启动
CMD ["sh", "-c", "alembic upgrade head && uvicorn careercrew_api.main:app --host 0.0.0.0 --port 8000"]
