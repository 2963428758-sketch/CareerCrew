"""MinerU 云端精准解析 API loader（R6，provider=api）。

本机零推理负载：文件上传到 MinerU 云端（POST /api/v4/file-urls/batch ->
PUT 上传原始字节 -> 系统自动提交任务），轮询
GET /api/v4/extract-results/batch/{batch_id}，完成后下载 zip 解压，
再复用 mineru_common.build_parsed_document 组装与本地 loader 一致的
ParsedDocument（页面 Markdown + 对象块 + 整页 PNG）。

官方文档：https://mineru.net/apiManage/docs
- 文件 <=200MB、<=200 页；每天前 1000 页最高优先级
- 上传时无须设置 Content-Type；上传完成后系统自动提交解析任务
- 批量结果端点未在官方页列出，为 v4 批量任务轮询端点（LightRAG / MCP server 实现一致）

失败统一抛 ParsingError（调用方记 doc_type=error 跳过，不中断批量入库）。
"""
from __future__ import annotations

import ssl
import time
import zipfile
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

from careercrew_core.rag.loaders.base_loader import ParsedDocument
from careercrew_core.rag.loaders.mineru_common import (
    ParsingError,
    build_parsed_document,
    sanitize_doc_id,
)

_API_BASE = "https://mineru.net"
_MAX_FILE_SIZE = 200 * 1024 * 1024
_DONE_STATES = {"done"}
_ACTIVE_STATES = {"pending", "running", "converting", "waiting-file", "queued"}


class _StableTLSAdapter(HTTPAdapter):
    """OSS 网关对 urllib3 默认 ssl context（OP_NO_TICKET/自定义 ciphers）会间歇性
    TLS 断连（SSLEOFError: UNEXPECTED_EOF_WHILE_READING，实测 ~50% 失败率）。

    这里显式传入 Python 默认 ssl context 绕过 urllib3 的那些选项（实测成功率 90%+）；
    ALPN 无需干预——urllib3 2.x 的 ssl_wrap_socket 会无条件覆盖为 ["http/1.1"]。
    """

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = ssl.create_default_context()
        return super().init_poolmanager(*args, **kwargs)


class MinerUApiLoader:
    """MinerU 云端精准解析：上传 -> 轮询 -> 下载 zip -> ParsedDocument。"""

    def __init__(
        self,
        output_dir: str | Path,
        api_key: str,
        model_version: str = "vlm",
        formula: bool = True,
        table: bool = True,
        language: str = "ch",
        poll_interval: int = 5,
        timeout: int = 1800,
        base_url: str = _API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ParsingError("MinerU API key 未设置（配置 rag.loaders.api_key / MINERU_API_KEY）")
        self._output_dir = Path(output_dir)
        self._api_key = api_key
        self._model_version = model_version
        self._formula = formula
        self._table = table
        self._language = language
        self._poll_interval = max(int(poll_interval), 1)
        self._timeout = max(int(timeout), 30)
        self._base_url = base_url.rstrip("/")
        self._session = session or self._make_session()

    @staticmethod
    def _make_session() -> requests.Session:
        sess = requests.Session()
        sess.mount("https://", _StableTLSAdapter())
        return sess

    def _drop_connections(self) -> None:
        """清空连接池：TLS 断连后旧连接不可信，重试前强制新建连接。"""
        try:
            self._session.close()
        except Exception:
            pass

    def parse(self, path: str | Path) -> ParsedDocument:
        """解析文件 -> ParsedDocument（页面 + 对象块 + 整页图）。"""
        src = Path(path)
        size = src.stat().st_size
        if size > _MAX_FILE_SIZE:
            raise ParsingError(f"MinerU API 限制单文件 <=200MB（{src} 为 {size / 1024 / 1024:.1f}MB）")
        doc_id = sanitize_doc_id(src.stem)
        data_id = doc_id
        out_root = self._output_dir / doc_id
        out_root.mkdir(parents=True, exist_ok=True)

        batch_id = self._submit(src, data_id)
        full_zip_url = self._poll(batch_id, data_id, src.name)
        zip_path = self._download_zip(full_zip_url, out_root)
        content_root = self._extract_zip(zip_path, out_root)
        return build_parsed_document(doc_id, src, out_root, content_root)

    def _request(
        self,
        method: str,
        url: str,
        *,
        max_retries: int = 3,
        backoff: float = 2.0,
        **kwargs,
    ) -> requests.Response:
        """带指数退避重试的请求（云端间歇性 TLS 断连时自动重试）。"""
        last = ""
        for attempt in range(max_retries):
            try:
                resp = getattr(self._session, method)(url, **kwargs)
                if resp.status_code < 500:
                    return resp
                last = f"HTTP {resp.status_code} {resp.text[:200]}"
            except requests.RequestException as e:
                last = str(e)
                self._drop_connections()  # TLS 断连：旧连接不可信，下次新建
            if attempt < max_retries - 1:
                time.sleep(backoff * (attempt + 1))
        raise ParsingError(f"MinerU API 请求失败（{method.upper()} {url}）: {last}")

    def _submit(self, src: Path, data_id: str) -> str:
        """申请上传链接 -> PUT 原始字节 -> 返回 batch_id（系统自动提交任务）。"""
        url = f"{self._base_url}/api/v4/file-urls/batch"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"}
        payload = {
            "files": [{"name": src.name, "data_id": data_id}],
            "model_version": self._model_version,
            "enable_formula": self._formula,
            "enable_table": self._table,
            "language": self._language,
        }
        try:
            resp = self._request("post", url, headers=headers, json=payload, timeout=60)
        except ParsingError as e:
            raise ParsingError(f"MinerU API 申请上传链接失败（{src}）: {e}") from e
        body = resp.json()
        if body.get("code") != 0:
            raise ParsingError(f"MinerU API 申请上传链接失败（{src}）: {body.get('msg') or body}")
        data = body.get("data") or {}
        batch_id = data.get("batch_id") or ""
        urls = data.get("file_urls") or []
        if not batch_id or not urls:
            raise ParsingError(f"MinerU API 响应缺少 batch_id/file_urls: {body}")

        self._upload_file(urls[0], src)
        return batch_id

    def _upload_file(self, url: str, src: Path) -> None:
        """PUT 原始字节（文档要求不设 Content-Type），失败自动重试（最多 5 次）。"""
        last = ""
        for attempt in range(5):
            try:
                with src.open("rb") as f:
                    up = self._session.put(url, data=f, timeout=300)
                if up.status_code == 200:
                    return
                last = f"HTTP {up.status_code} {up.text[:200]}"
            except requests.RequestException as e:
                last = str(e)
                self._drop_connections()  # OSS 偶发 TLS 断连：清连接池，下次全新连接
            if attempt < 4:
                time.sleep(2 * (attempt + 1))
        raise ParsingError(f"MinerU API 文件上传失败（{src}）: {last}")

    def _poll(self, batch_id: str, data_id: str, filename: str) -> str:
        """轮询批量结果直到本文件 done，返回 full_zip_url。"""
        url = f"{self._base_url}/api/v4/extract-results/batch/{batch_id}"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"}
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                resp = self._request("get", url, headers=headers, timeout=60)
            except ParsingError as e:
                raise ParsingError(f"MinerU API 查询任务失败（{filename}）: {e}") from e
            body = resp.json()
            if body.get("code") != 0:
                raise ParsingError(f"MinerU API 查询任务失败（{filename}）: {body.get('msg') or body}")
            entry = self._find_entry(body.get("data"), data_id, filename)
            if entry is None:
                raise ParsingError(f"MinerU API 未找到任务结果（{filename}，batch {batch_id}）")
            state = str(entry.get("state") or "")
            if state in _DONE_STATES:
                full_zip_url = str(entry.get("full_zip_url") or "")
                if not full_zip_url:
                    raise ParsingError(f"MinerU API 任务完成但缺少 zip 链接（{filename}）: {entry}")
                return full_zip_url
            if state == "failed":
                raise ParsingError(f"MinerU API 解析失败（{filename}）: {entry.get('err_msg') or entry}")
            if state not in _ACTIVE_STATES:
                raise ParsingError(f"MinerU API 未知状态 {state!r}（{filename}）: {entry}")
            if time.monotonic() >= deadline:
                raise ParsingError(f"MinerU API 解析超时（{filename}，等待 >{self._timeout}s）")
            time.sleep(self._poll_interval)

    @staticmethod
    def _find_entry(data, data_id: str, filename: str) -> dict | None:
        """批量结果可能是 list[dict] 或 {name: dict}，按 data_id/文件名匹配。"""
        stem = Path(filename).stem
        if isinstance(data, dict):
            # 实测批量结果形如 {"batch_id": ..., "extract_result": [...]}
            for key in ("extract_result", "results", "tasks", "files"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
            else:
                for key in (data_id, filename, stem):
                    if key in data and isinstance(data[key], dict):
                        return data[key]
                for v in data.values():
                    if isinstance(v, dict):
                        return v
                return None
        if isinstance(data, list):
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                ident = str(entry.get("data_id") or entry.get("name") or entry.get("file_name") or "")
                if ident and ident in (data_id, filename, stem):
                    return entry
            if len(data) == 1 and isinstance(data[0], dict):
                return data[0]
        return None

    def _download_zip(self, full_zip_url: str, out_root: Path) -> Path:
        zip_path = out_root / "result.zip"
        last = ""
        for attempt in range(3):
            try:
                with self._session.get(full_zip_url, stream=True, timeout=300) as resp:
                    resp.raise_for_status()
                    with zip_path.open("wb") as f:
                        for chunk in resp.iter_content(chunk_size=1 << 16):
                            if chunk:
                                f.write(chunk)
                return zip_path
            except (requests.RequestException, OSError) as e:
                last = str(e)
                self._drop_connections()
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
        raise ParsingError(f"MinerU API 下载结果 zip 失败: {last}")

    def _extract_zip(self, zip_path: Path, out_root: Path) -> Path:
        target = out_root / "zip"
        target.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for member in zf.infolist():
                    dest = (target / member.filename).resolve()
                    if not dest.is_relative_to(target.resolve()):
                        raise ParsingError(f"MinerU API zip 包含非法路径: {member.filename}")
                zf.extractall(target)
        except zipfile.BadZipFile as e:
            raise ParsingError(f"MinerU API 结果 zip 损坏: {e}") from e
        return target
