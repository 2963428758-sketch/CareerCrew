"""browser 路由：Chrome CDP 采集器状态检测与一键启动。

提供给前端求职页（MatcherPage）：
- GET /api/browser/cdp-status: 检测 9222 调试端口连通性及 Boss直聘 / 猎聘 打开状态
- POST /api/browser/launch-cdp: 本地一键唤起带 9222 端口的已登录 Chrome
- GET /api/browser/cdp-command: 获取手动执行的命令与批处理脚本路径
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from careercrew_core.state.settings import load_settings

logger = logging.getLogger(__name__)

router = APIRouter()

_DEFAULT_CDP_URL = "http://127.0.0.1:9222"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PS1_SCRIPT = _PROJECT_ROOT / "scripts" / "start_chrome_cdp.ps1"
_BAT_SCRIPT = _PROJECT_ROOT / "scripts" / "start_chrome_cdp.bat"


def _get_cdp_base_url() -> str:
    try:
        cfg = load_settings().tools.search
        url = (getattr(cfg, "boss_cdp_url", "") or "").strip()
        if url:
            return url.rstrip("/")
    except Exception:
        pass
    return _DEFAULT_CDP_URL


def _check_cdp_alive(base_url: str, timeout: float = 1.2) -> tuple[bool, list[dict[str, Any]]]:
    """通过 HTTP 探测 CDP 端点及标签页列表。"""
    version_url = f"{base_url}/json/version"
    try:
        req = urllib.request.Request(version_url, headers={"User-Agent": "CareerCrew-Check"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False, []
    except Exception:
        return False, []

    list_url = f"{base_url}/json/list"
    tabs: list[dict[str, Any]] = []
    try:
        req = urllib.request.Request(list_url, headers={"User-Agent": "CareerCrew-Check"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw = resp.read().decode("utf-8", errors="ignore")
                data = json.loads(raw)
                if isinstance(data, list):
                    tabs = data
    except Exception:
        pass

    return True, tabs


@router.get("/browser/cdp-status")
async def get_cdp_status() -> dict[str, Any]:
    """检查本地 Chrome CDP 调试服务状态。"""
    base_url = _get_cdp_base_url()
    alive, tabs = _check_cdp_alive(base_url)

    boss_opened = False
    liepin_opened = False
    for tab in tabs:
        url = str(tab.get("url", "")).lower()
        if "zhipin.com" in url:
            boss_opened = True
        if "liepin.com" in url:
            liepin_opened = True

    return {
        "connected": alive,
        "cdp_url": base_url,
        "boss_opened": boss_opened,
        "liepin_opened": liepin_opened,
        "tab_count": len(tabs),
        "command": "powershell -ExecutionPolicy Bypass -File scripts/start_chrome_cdp.ps1",
        "bat_path": str(_BAT_SCRIPT.relative_to(_PROJECT_ROOT)) if _BAT_SCRIPT.exists() else "scripts/start_chrome_cdp.bat",
        "message": "Chrome 调试服务已连接" if alive else "Chrome 调试服务未启动",
    }


@router.post("/browser/launch-cdp")
async def launch_cdp() -> dict[str, Any]:
    """一键在宿主机启动带调试端口的 Chrome 浏览器。"""
    base_url = _get_cdp_base_url()
    alive, _ = _check_cdp_alive(base_url, timeout=0.8)
    if alive:
        return {
            "status": "already_running",
            "connected": True,
            "cdp_url": base_url,
            "message": "Chrome 调试服务已在运行中，无需重复启动。",
        }

    if not _PS1_SCRIPT.exists():
        return {
            "status": "error",
            "connected": False,
            "cdp_url": base_url,
            "message": f"启动脚本未找到：{_PS1_SCRIPT}",
        }

    try:
        if os.name == "nt":
            # 直接使用 cmd.exe /c start 唤起独立的 PowerShell 窗口执行 start_chrome_cdp.ps1
            # 避免 cmd.exe 直接解析 .bat 文件时因 Windows 默认 ANSI/GBK 导致的编码错乱
            cmd_str = f'cmd.exe /c start "CareerCrew Chrome CDP" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{_PS1_SCRIPT}"'
            logger.info("launching Chrome CDP via: %s", cmd_str)
            subprocess.Popen(cmd_str, shell=True)
        else:
            cmd = ["bash", str(_PROJECT_ROOT / "scripts" / "start_chrome_cdp.sh")]
            subprocess.Popen(cmd)

        return {
            "status": "launched",
            "connected": False,
            "cdp_url": base_url,
            "message": "已调起 Chrome 启动脚本！请在弹出的 Chrome 窗口中分别登录 Boss直聘 与 猎聘。",
        }

    except Exception as e:
        logger.error("failed to launch Chrome CDP: %s", e, exc_info=True)
        return {
            "status": "error",
            "connected": False,
            "cdp_url": base_url,
            "message": f"启动 Chrome 失败：{e}。请手动运行 scripts/start_chrome_cdp.ps1",
        }
