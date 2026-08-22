"""统一日志配置：LOG_LEVEL 环境变量入口 + request_id 请求关联。

用法（应用入口一次性调用）：
    from careercrew_api.logging_config import setup_logging
    setup_logging()

request_id 通过 ContextVar 传递：middleware 从 X-Request-ID 头取或生成 uuid 前 12 位，
所有经 root logger 输出的记录自动携带 [%(request_id)s]，响应头回写便于用户反馈定位。
"""
from __future__ import annotations

import contextvars
import logging
import os
import uuid

# task-per-request 隔离：每个 HTTP 请求在独立 asyncio task 中执行，
# set 后无需 reset（流式响应体在 middleware 返回后仍需保留该值）。
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """把当前 request_id 注入每条 LogRecord（format 占位 %(request_id)s）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    return rid


def setup_logging(level: str | None = None) -> None:
    """配置 root logger（幂等：清空重建，避免重复 handler）。

    level 优先级：显式参数 > LOG_LEVEL 环境变量 > INFO。
    """
    lvl_name = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    lvl = getattr(logging, lvl_name, logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s")
    )
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(lvl)
