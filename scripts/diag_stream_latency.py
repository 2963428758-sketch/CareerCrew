"""流式延迟诊断：分层测量 首token时间(TTFT) / 总耗时 / 每token间隔。

A. 裸 HTTP SSE（httpx 直连硅基流动）——网络+供应商基线
B. langchain create_llm().stream()——框架层开销 = B - A
C. langchain create_llm().invoke()——非流式总时长对照

用法：
    python scripts/diag_stream_latency.py [--proxy http://127.0.0.1:7890]
只依赖 stdlib + httpx（env 已有）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

PROMPT = "用一句话介绍你自己"


def _cfg() -> tuple[str, str, str]:
    sys.path.insert(0, str(ROOT))
    from careercrew_core.state.settings import load_settings

    s = load_settings()
    return s.llm.base_url, s.llm.api_key, s.llm.model


def raw_sse(base_url: str, api_key: str, model: str) -> None:
    import httpx

    url = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": True,
        "max_tokens": 128,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    t0 = time.perf_counter()
    first = None
    n = 0
    with httpx.Client(timeout=60) as client:
        with client.stream("POST", url, json=body, headers=headers) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                delta = json.loads(payload)["choices"][0]["delta"].get("content", "")
                if delta and first is None:
                    first = time.perf_counter() - t0
                if delta:
                    n += 1
    total = time.perf_counter() - t0
    print(f"[A] 裸SSE   : TTFT={first:.2f}s total={total:.2f}s chunks={n}"
          if first else f"[A] 裸SSE   : 无内容! total={total:.2f}s")


def lc_stream(base_url: str, api_key: str, model: str) -> None:
    from langchain_core.messages import HumanMessage

    from careercrew_ai.llm.llm_adapter import create_llm
    from careercrew_core.state.settings import load_settings

    llm = create_llm(load_settings(), max_tokens=128)
    t0 = time.perf_counter()
    first = None
    gaps: list[float] = []
    last = t0
    n = 0
    for chunk in llm.stream([HumanMessage(content=PROMPT)]):
        text = chunk.content if isinstance(chunk.content, str) else ""
        if not text:
            continue
        now = time.perf_counter()
        if first is None:
            first = now - t0
        else:
            gaps.append(now - last)
        last = now
        n += 1
    total = time.perf_counter() - t0
    avg_gap = (sum(gaps) / len(gaps)) if gaps else 0.0
    print(f"[B] LC流式 : TTFT={first:.2f}s total={total:.2f}s chunks={n} 平均chunk间隔={avg_gap * 1000:.0f}ms"
          if first is not None else f"[B] LC流式 : 无内容! total={total:.2f}s")


def lc_invoke(base_url: str, api_key: str, model: str) -> None:
    from langchain_core.messages import HumanMessage

    from careercrew_ai.llm.llm_adapter import create_llm
    from careercrew_core.state.settings import load_settings

    llm = create_llm(load_settings(), max_tokens=128)
    t0 = time.perf_counter()
    msg = llm.invoke([HumanMessage(content=PROMPT)])
    total = time.perf_counter() - t0
    print(f"[C] invoke : total={total:.2f}s len={len(msg.content)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", default=None, help="如 http://127.0.0.1:7890")
    args = ap.parse_args()
    if args.proxy:
        os.environ["HTTPS_PROXY"] = args.proxy
        os.environ["HTTP_PROXY"] = args.proxy
        print(f"使用代理: {args.proxy}")
    else:
        # 显式清掉继承的代理变量，测直连基线
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
            os.environ.pop(k, None)

    base_url, api_key, model = _cfg()
    masked = api_key[:8] + "..." if api_key else "<empty>"
    print(f"model={model} base_url={base_url} key={masked}\n")

    raw_sse(base_url, api_key, model)
    lc_stream(base_url, api_key, model)
    lc_invoke(base_url, api_key, model)


if __name__ == "__main__":
    main()
