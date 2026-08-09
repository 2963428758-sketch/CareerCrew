"""careercrew_api - FastAPI 后端（与 CLI 平级的组合根）。

双服务本地开发：uvicorn :8000（API）+ vite :5173（前端）。
生产模式：npm run build -> FastAPI StaticFiles 托管 web/dist（SPA fallback）。
"""
