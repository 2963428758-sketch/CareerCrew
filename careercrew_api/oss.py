"""阿里云 OSS 头像存储：无第三方依赖的 V1 预签名 PUT/GET（标准库实现）。

配置来自 config/settings.yaml 的 ``oss`` 段（值经 .env 环境变量替换）：
    endpoint            Endpoint（如 oss-cn-beijing.aliyuncs.com）
    access_key_id       AccessKey ID
    access_key_secret   AccessKey Secret
    bucket_name         Bucket 名（如 oceanverse）
    dir_prefix          对象键前缀（头像最终落在 {dir_prefix}/avatars/...）

说明：
- 头像文件较小，使用 OSS V1 预签名 URL 直传/直读，不引入 oss2 依赖；
- 读取经 API 同源代理（避免浏览器跨域 CORS 问题），Bucket 无需公开读权限；
- access_key 四项任一未配置时返回 None，调用方回退本地存储。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse
import urllib.request
from functools import lru_cache


@lru_cache(maxsize=1)
def _load_oss_settings():
    from careercrew_core.state.settings import load_settings

    return load_settings().oss


def oss_config() -> dict | None:
    """读取 OSS 配置；access_key 四项缺一即视为未配置（回退本地存储）。"""
    settings = _load_oss_settings()
    ak = (settings.access_key_id or "").strip()
    sk = (settings.access_key_secret or "").strip()
    bucket = (settings.bucket_name or "").strip()
    endpoint = (settings.endpoint or "").strip()
    if not (ak and sk and bucket and endpoint):
        return None
    prefix = (settings.dir_prefix or "").strip().strip("/")
    return {"ak": ak, "sk": sk, "bucket": bucket, "endpoint": endpoint, "dir_prefix": prefix}


def _sign(secret: str, string_to_sign: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def presign_put(config: dict, key: str, content_type: str, expires: int = 1800) -> str:
    """PUT 预签名（携带 Content-Type，上传时必须发送相同 Content-Type 头）。"""
    deadline = int(time.time()) + expires
    string_to_sign = f"PUT\n\n{content_type}\n{deadline}\n/{config['bucket']}/{key}"
    query = urllib.parse.urlencode({
        "OSSAccessKeyId": config["ak"],
        "Expires": str(deadline),
        "Signature": _sign(config["sk"], string_to_sign),
    })
    return f"https://{config['bucket']}.{config['endpoint']}/{urllib.parse.quote(key, safe='/')}?{query}"


def presign_get(config: dict, key: str, expires: int = 900) -> str:
    """GET 预签名（无 Content-Type；用于同源代理拉取对象内容）。"""
    deadline = int(time.time()) + expires
    string_to_sign = f"GET\n\n\n{deadline}\n/{config['bucket']}/{key}"
    query = urllib.parse.urlencode({
        "OSSAccessKeyId": config["ak"],
        "Expires": str(deadline),
        "Signature": _sign(config["sk"], string_to_sign),
    })
    return f"https://{config['bucket']}.{config['endpoint']}/{urllib.parse.quote(key, safe='/')}?{query}"


def upload_bytes(config: dict, key: str, data: bytes, content_type: str) -> None:
    """通过预签名 PUT 直传字节内容；非 200 响应抛 RuntimeError（含 OSS 返回的 XML 原因）。"""
    url = presign_put(config, key, content_type)
    request = urllib.request.Request(url, data=data, method="PUT")
    request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError(f"OSS PUT failed: HTTP {response.status}")
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"OSS PUT failed: HTTP {err.code} {err.reason} {body[:400]}") from err


def download_bytes(config: dict, key: str) -> bytes:
    """通过预签名 GET 拉取对象内容（API 同源代理读取，避免跨域 CORS 问题）。"""
    url = presign_get(config, key)
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError(f"OSS GET failed: HTTP {response.status}")
            return response.read()
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"OSS GET failed: HTTP {err.code} {err.reason} {body[:400]}") from err
