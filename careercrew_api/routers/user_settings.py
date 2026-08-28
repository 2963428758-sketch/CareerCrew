"""用户个性化设置路由：支持用户配置与测试自身的大模型 API Key（DashScope/通义千问等）。"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from careercrew_api.auth.dependencies import CurrentUser, get_auth_service
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime

logger = logging.getLogger(__name__)

router = APIRouter()


class ApiKeySettingsResponse(BaseModel):
    has_key: bool
    masked_key: str = ""
    provider: str = "dashscope"
    system_configured: bool = False


class ApiKeyUpdateRequest(BaseModel):
    api_key: str


class ApiKeyTestRequest(BaseModel):
    api_key: str
    provider: str = "dashscope"


class ApiKeyTestResponse(BaseModel):
    ok: bool
    message: str


def _mask_api_key(key: str) -> str:
    s = key.strip()
    if not s:
        return ""
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}{'*' * min(len(s) - 8, 20)}{s[-4:]}"


@router.get("/settings/apikey", response_model=ApiKeySettingsResponse)
def get_apikey_settings(
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> ApiKeySettingsResponse:
    """获取当前用户的 API Key 配置状态（仅返回脱敏信息，不泄露完整明文）。"""
    store = get_auth_service().store
    user_settings = store.get_user_settings(current_user["id"])
    custom_key = (
        user_settings.get("dashscope_api_key")
        or user_settings.get("api_key")
        or ""
    ).strip()

    llm_cfg = getattr(rt.settings, "llm", None) if rt.settings else None
    system_key = (getattr(llm_cfg, "api_key", "") or "").strip() if llm_cfg else ""
    system_configured = bool(system_key and "${" not in system_key)

    return ApiKeySettingsResponse(
        has_key=bool(custom_key),
        masked_key=_mask_api_key(custom_key),
        provider="dashscope",
        system_configured=system_configured,
    )


@router.put("/settings/apikey")
def update_apikey_settings(
    req: ApiKeyUpdateRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    """保存当前用户的 DashScope API Key。"""
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")

    store = get_auth_service().store
    user_settings = store.get_user_settings(current_user["id"])
    user_settings["dashscope_api_key"] = key
    store.save_user_settings(current_user["id"], user_settings)

    # 驱逐该用户的运行时 LLM 缓存，使新 Key 立即生效
    if hasattr(rt, "_user_llms") and hasattr(rt, "_user_llms_lock"):
        with rt._user_llms_lock:
            rt._user_llms.pop(current_user["id"], None)

    return {"ok": True, "masked_key": _mask_api_key(key)}


@router.delete("/settings/apikey")
def delete_apikey_settings(
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, bool]:
    """清空当前用户的自定义 API Key（恢复使用系统默认密钥）。"""
    store = get_auth_service().store
    user_settings = store.get_user_settings(current_user["id"])
    user_settings.pop("dashscope_api_key", None)
    user_settings.pop("api_key", None)
    store.save_user_settings(current_user["id"], user_settings)

    if hasattr(rt, "_user_llms") and hasattr(rt, "_user_llms_lock"):
        with rt._user_llms_lock:
            rt._user_llms.pop(current_user["id"], None)

    return {"ok": True}


@router.post("/settings/apikey/test", response_model=ApiKeyTestResponse)
def test_apikey_settings(
    req: ApiKeyTestRequest,
    _current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> ApiKeyTestResponse:
    """连通性测试：调用阿里云百炼进行 1 Token 极简生成，验证 Key 是否有效。"""
    key = req.api_key.strip()
    if not key:
        return ApiKeyTestResponse(ok=False, message="API Key 不能为空")

    try:
        from langchain.chat_models import init_chat_model
        from langchain_core.messages import HumanMessage

        model_name = "qwen-plus"
        base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        if rt.settings:
            llm_cfg = getattr(rt.settings, "llm", None)
            if llm_cfg:
                model_name = getattr(llm_cfg, "model", None) or model_name
                base_url = getattr(llm_cfg, "base_url", None) or base_url

        test_llm = init_chat_model(
            model=model_name,
            model_provider="openai",
            base_url=base_url,
            api_key=key,
            max_tokens=5,
            timeout=10,
            max_retries=0,
        )
        test_llm.invoke([HumanMessage(content="hi")])
        return ApiKeyTestResponse(ok=True, message="DashScope 连通性测试成功！密钥有效且模型已响应。")
    except Exception as e:
        err_msg = str(e)
        logger.warning("DashScope test failed: %s", err_msg)
        if "401" in err_msg or "InvalidApiKey" in err_msg or "AuthenticationError" in err_msg:
            return ApiKeyTestResponse(ok=False, message="API Key 认证失败：密钥不存在或未激活")
        if "timeout" in err_msg.lower() or "timed out" in err_msg.lower():
            return ApiKeyTestResponse(ok=False, message="请求超时，请检查服务器网络连接")
        return ApiKeyTestResponse(ok=False, message=f"连接失败: {err_msg[:120]}")
