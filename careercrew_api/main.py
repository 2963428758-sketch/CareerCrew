"""FastAPI 应用：CORS + /api 挂载 + 生产托管 careercrew_web/dist（SPA fallback）。

开发：uvicorn careercrew_api.main:app --reload --port 8000（+ vite :5175 代理 /api）
生产：npm run build -> uvicorn 单端口托管 careercrew_web/dist（SPA fallback 到 index.html）
"""
from __future__ import annotations

import logging
import threading
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from careercrew_api.auth.middleware import TrustedOriginMiddleware
from careercrew_api.routers import (
    agent,
    attachments,
    auth,
    chat,
    consult,
    context,
    data,
    feedback,
    interview,
    knowledge,
    quality,
    resume,
    threads,
)
from careercrew_api.runtime import RuntimeInitError
from careercrew_core.state.settings import load_auth_settings

logger = logging.getLogger("careercrew_api")

DIST = Path(__file__).resolve().parents[1] / "careercrew_web" / "dist"


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _validation_detail(errors: list[dict]) -> str:
    """把 FastAPI 参数校验错误转成中文提示；自定义校验器已是中文则直接使用。"""
    parts: list[str] = []
    for err in errors[:3]:
        msg = str(err.get("msg", ""))
        if _has_cjk(msg):
            parts.append(msg)
            continue
        loc = [
            str(p) for p in err.get("loc", [])
            if p not in ("body", "query", "path", "header", "cookie")
        ]
        field = ".".join(loc) or "参数"
        parts.append(f"「{field}」填写不正确")
    return "；".join(parts) or "请求参数不正确，请检查后重试"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """过期/长期吊销刷新会话清理（守护线程，避免阻塞事件循环）。"""
    from careercrew_api.auth.dependencies import get_auth_service
    from careercrew_api.dream import start_dream_scheduler

    stop = threading.Event()
    interval = max(get_auth_service().settings.cleanup_interval_hours, 1) * 3600

    def _loop() -> None:
        while not stop.wait(interval):
            try:
                get_auth_service().store.delete_expired_refresh_sessions()
            except Exception:
                pass  # 清理失败不中断服务；下一轮重试

    thread = threading.Thread(target=_loop, name="refresh-session-cleanup", daemon=True)
    thread.start()

    # Auto Dream：每日低峰 consolidation（memory.consolidation.dream_schedule="HH:MM" 开启，off 关闭）
    from careercrew_api.deps import get_runtime_dep

    rt = get_runtime_dep()
    schedule = ""
    try:
        if getattr(rt, "settings", None) is not None:
            schedule = rt.settings.memory.consolidation.dream_schedule
    except Exception:
        pass
    start_dream_scheduler(get_runtime_dep, get_auth_service, schedule, stop)

    yield
    stop.set()


def create_app() -> FastAPI:
    # 重组件保持惰性初始化，但认证生产配置必须在启动时 fail-fast。
    auth_settings = load_auth_settings()
    app = FastAPI(title="CareerCrew API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        TrustedOriginMiddleware, allowed_origins=list(auth_settings.trusted_origins)
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(auth_settings.trusted_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # /api 路由
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    # threads（conversation Source of Truth）先于 data 注册，故 POST/PATCH/DELETE
    # /api/threads 及 /api/threads/{id}/messages|clear|export、/api/messages/{id}/regenerate
    # 均由 threads.py 接管；data.py 仍定义 GET /api/threads（memory 列表）与其
    # PATCH/DELETE 旧路由，但后者已被 threads.py 的同路径路由遮蔽（保留供兼容引用）。
    app.include_router(threads.router, prefix="/api", tags=["threads"])
    app.include_router(feedback.router, prefix="/api", tags=["feedback"])
    app.include_router(quality.router, prefix="/api/quality", tags=["quality"])
    app.include_router(data.router, prefix="/api", tags=["data"])
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(interview.router, prefix="/api/interview", tags=["interview"])
    app.include_router(resume.router, prefix="/api/resume", tags=["resume"])
    app.include_router(consult.router, prefix="/api/consult", tags=["consult"])
    app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])
    app.include_router(context.router, prefix="/api/context", tags=["context"])
    app.include_router(attachments.router, prefix="/api/chat/attachments", tags=["attachments"])
    app.include_router(agent.router, prefix="/api", tags=["agent"])

    # 生产模式：托管 careercrew_web/dist（SPA fallback）
    if DIST.exists():
        # 静态资源（JS/CSS/图片）直接托管
        app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

        # SPA fallback：非 /api 路径 -> index.html（支持前端路由如 /interview）
        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            file_path = DIST / full_path
            if full_path and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(str(DIST / "index.html"))

    # ── 全局异常处理：所有未捕获异常统一返回中文 JSON，不再出现英文 "Internal Server Error" ──
    @app.exception_handler(RuntimeInitError)
    async def runtime_init_error_handler(_request: Request, exc: RuntimeInitError) -> JSONResponse:
        """重组件初始化失败（向量库连接等）→ 503，用户可见中文提示。"""
        msg = str(exc).strip()
        if not _has_cjk(msg):
            msg = "AI 服务初始化失败，请检查后端配置后重试"
        logger.error("Runtime init error: %s", exc)
        return JSONResponse(status_code=503, content={"detail": f"AI 服务暂不可用：{msg}"})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """请求参数校验失败 → 422，把英文校验错误汇总成中文提示。"""
        return JSONResponse(status_code=422, content={"detail": _validation_detail(exc.errors())})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """兜底：未处理异常 → 500 中文提示，完整堆栈打到服务端日志便于排查。"""
        logger.error(
            "Unhandled error on %s %s: %s\n%s",
            request.method, request.url.path, exc, traceback.format_exc(),
        )
        return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})

    return app


app = create_app()
