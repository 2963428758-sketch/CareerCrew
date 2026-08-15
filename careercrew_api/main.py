"""FastAPI 应用：CORS + /api 挂载 + 生产托管 careercrew_web/dist（SPA fallback）。

开发：uvicorn careercrew_api.main:app --reload --port 8000（+ vite :5175 代理 /api）
生产：npm run build -> uvicorn 单端口托管 careercrew_web/dist（SPA fallback 到 index.html）
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from careercrew_api.auth.middleware import TrustedOriginMiddleware
from careercrew_api.routers import auth, chat, consult, data, interview, knowledge, resume, threads
from careercrew_core.state.settings import load_auth_settings

DIST = Path(__file__).resolve().parents[1] / "careercrew_web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """过期/长期吊销刷新会话清理（守护线程，避免阻塞事件循环）。"""
    from careercrew_api.auth.dependencies import get_auth_service

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
    # threads（conversation Source of Truth）先于 data 注册：POST /api/threads 归 conversation；
    # data.py 仍提供 GET/PATCH/DELETE /api/threads（memory 线程列表与元数据）。
    app.include_router(threads.router, prefix="/api", tags=["threads"])
    app.include_router(data.router, prefix="/api", tags=["data"])
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(interview.router, prefix="/api/interview", tags=["interview"])
    app.include_router(resume.router, prefix="/api/resume", tags=["resume"])
    app.include_router(consult.router, prefix="/api/consult", tags=["consult"])
    app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])

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

    return app


app = create_app()

