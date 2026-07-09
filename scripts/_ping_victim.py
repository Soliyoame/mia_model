"""最小连通测试:给 victim 端点连发几次极短请求,看它现在是正常 / 慢 / 524。

用项目真实配置(.env + rag_config + llm_profiles)构造 victim 客户端,所以测的就是
baseline/PCV 实际会用的那个端点与模型(当前 = qwen3.5-397b @ littlesheep)。

用法:
    python scripts/_ping_victim.py          # 默认连发 3 次
    python scripts/_ping_victim.py 5         # 连发 5 次

每次只发一句话、max_tokens=16,花费极小;逐次打印耗时与结果,末尾给成功率小结。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)  # 保证 .env 与相对路径都从项目根解析,无论从哪个目录运行

from src.llm.factory import build_victim_client, load_llm_profiles, resolve_llm_profile_name
from src.utils.io import load_yaml


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    per_timeout = 60.0  # 单次超时(秒);littlesheep 的 524 是网关层超时,客户端调大也救不回,仅用于封顶等待

    rag = load_yaml("configs/rag_config.yaml")
    profiles = load_llm_profiles(rag)
    name = resolve_llm_profile_name("victim", config_profile=rag.get("generation", {}).get("victim_profile"))
    victim, prof = build_victim_client(profiles, profile_name=name)

    print(f"victim profile = {prof}")
    print(f"连发 {n} 次极短请求(每次 timeout={per_timeout:.0f}s)...\n")

    ok = 0
    for i in range(1, n + 1):
        t = time.time()
        try:
            out = victim.generate("Reply with a single word: hello", temperature=0.0, timeout=per_timeout, max_tokens=16)
            dt = time.time() - t
            ok += 1
            print(f"[{i}/{n}] OK   {dt:6.1f}s  响应={out!r}")
        except Exception as exc:  # noqa: BLE001
            dt = time.time() - t
            print(f"[{i}/{n}] FAIL {dt:6.1f}s  错误={str(exc)[:160]}")

    print(f"\n小结: {ok}/{n} 成功。", end="")
    if ok == n:
        print("端点正常(若耗时偏大,全量跑会慢但能靠重试兜)。")
    elif ok:
        print("端点偶发失败(可重试兜底,但密集调用如 IA 会很痛)。")
    else:
        print("端点此刻不可用(全失败),建议错峰或排查 littlesheep。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
