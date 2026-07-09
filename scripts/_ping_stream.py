"""验证流式(stream)能否绕过 littlesheep 的 ~30s 网关 524。

背景:非流式请求要干等完整响应(连 'hello' 都要 25s),常踩 littlesheep 的 30s 红线 → 524。
流式请求:模型首 token 几秒就吐、之后持续有数据流 → Cloudflare 不会因"30s 无响应"掐断。

本脚本用项目真实 victim 配置(.env + rag_config + llm_profiles)手搓一次流式请求,打印:
  首 token 延迟 / 总耗时 / 响应文本 —— 据此判断流式能否救活这个端点。

用法: python scripts/_ping_stream.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from src.llm.factory import build_victim_client, load_llm_profiles, resolve_llm_profile_name
from src.llm.openai_compatible import normalize_chat_completions_url
from src.utils.env import load_dotenv
from src.utils.io import load_yaml


def main() -> int:
    rag = load_yaml("configs/rag_config.yaml")
    profiles = load_llm_profiles(rag)
    name = resolve_llm_profile_name("victim", config_profile=rag.get("generation", {}).get("victim_profile"))
    _, prof = build_victim_client(profiles, profile_name=name)  # 只取解析好的 profile

    load_dotenv()
    key = os.getenv(str(prof.get("api_key_env", "")), "")
    url = normalize_chat_completions_url(str(prof["base_url"]))

    payload = {
        "model": prof["model"],
        "messages": [{"role": "user", "content": "Count from 1 to 60, one number per line, nothing else."}],
        "temperature": 0.0,
        "max_tokens": 512,
        "stream": True,
        **(dict(prof.get("extra_body") or {})),
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "Mozilla/5.0 (compatible; conflict-mia/1.0)",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    print(f"流式请求 {url}\nmodel = {prof['model']}\n")

    t = time.time()
    first: float | None = None
    first_content: float | None = None
    chunks: list[str] = []
    reasoning: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw in resp:  # 逐行读 SSE 流(data: {...})
                line = raw.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                if first is None:
                    first = time.time() - t  # 首个数据块到达的延迟(TTFT)
                try:
                    delta = json.loads(data)["choices"][0].get("delta", {})
                    c = delta.get("content") or ""
                    rc = delta.get("reasoning_content") or ""  # 思考型模型把"思考"放这里
                    if c:
                        if first_content is None:
                            first_content = time.time() - t
                        chunks.append(c)
                    if rc:
                        reasoning.append(rc)
                except Exception:  # noqa: BLE001 — 个别非 JSON 行(心跳/注释)跳过
                    pass
        total = time.time() - t
        ans, think = "".join(chunks), "".join(reasoning)
        fc = f"{first_content:.1f}s" if first_content is not None else "(无)"
        print(f"OK   首字节={first:.1f}s  首答案={fc}  总耗时={total:.1f}s")
        print(f"     答案 content   = {ans!r}")
        print(f"     思考 reasoning = {len(think)} 字符  → 思考型模型?{'是' if think else '否'}")
        if first is not None and first < 30:
            print("\n=> 首数据 30s 内到达、持续有流 → 可绕过 30s 524。流式方案成立。")
        else:
            print("\n=> 首数据 >30s,流式可能仍被掐断;需另想办法。")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {time.time() - t:.1f}s  错误={str(exc)[:200]}")
        print("\n=> 流式也不行(littlesheep 不支持 stream,或更早就掐断)。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
