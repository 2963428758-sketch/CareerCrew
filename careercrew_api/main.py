"""FastAPI 应用：CORS + /api 挂载 + 生产托管 careercrew_web/dist（SPA fallback）。

开发：uvicorn careercrew_api.main:app --reload --port 8000（+ vite :5173 代理 /api）
生产：npm run build -> uvicorn 单端口托管 careercrew_web/dist（SPA fallback 到 index.html）
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from careercrew_api.routers import chat, consult, data, interview, knowledge, resume

DIST = Path(__file__).resolve().parents[1] / "careercrew_web" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="CareerCrew API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # /api 路由
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
