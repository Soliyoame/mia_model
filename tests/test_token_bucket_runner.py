"""令牌桶限速 + 并发抗卡顿的测试。

中文说明
========
验证类别 C 提速改动的两层性质:

1. TokenBucket 的【速率安全】:多线程并发抢令牌,全局发放速率恒 ≤ RPM(绝不超端点限流)。
   这是"不违规"的硬保证,单独用高 RPM 快速验。

2. 接入 run_rag_and_llm_only 后:
   - 【并发等价】workers=1 与 workers=4(+令牌桶) 跑出的 RAG / LLM-only 输出【逐字段一致】,
     证明并发不打乱/不丢/不重复结果(executor.map 保序 + process 无共享可变状态)。
   - 【抗卡顿】某些 call 变慢时,workers=4 的墙钟显著短于 workers=1,证明并发能在卡顿下
     把管道填满(这正是本次提速的本质:并发不为超 RPM,而为在抖动下仍达到 RPM)。

这些用例用确定性假 client(不打网络)+ 空检索替身,把关注点收敛到限速/并发本身。
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
import unittest
from unittest.mock import patch
import uuid

from src.rag.runner import TokenBucket, run_rag_and_llm_only
from src.utils.io import read_jsonl, write_jsonl


WORKSPACE_TMP = Path(__file__).resolve().parents[1] / ".pytest_tmp"


@contextmanager
def temporary_dir() -> Iterator[Path]:
    WORKSPACE_TMP.mkdir(exist_ok=True)
    path = WORKSPACE_TMP / f"tb_{uuid.uuid4().hex}"
    path.mkdir()
    yield path


class _FakeRetriever:
    """返回空检索的替身(本测试不关心 RAG 检索内容)。"""

    def __init__(self, *_a, **_k) -> None:
        pass

    def retrieve(self, _q: str, top_k: int = 5):
        return []


class _DetClient:
    """确定性假 client：response 是 prompt 的确定函数,故并发与串行输出必然一致。

    可选 per_call_sleep 模拟端点慢/卡顿,用于抗卡顿测试。
    """

    def __init__(self, per_call_sleep: float = 0.0) -> None:
        self.per_call_sleep = per_call_sleep
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, prompt: str, temperature: float = 0.0, timeout: float = 60.0, max_tokens: int = 512) -> str:
        if self.per_call_sleep:
            time.sleep(self.per_call_sleep)
        with self._lock:
            self.calls += 1
        mode = "rag" if "Reference information:" in prompt else "llm"
        # 只依赖 prompt 内容 → 确定性;取尾部片段区分不同 query。
        return f"resp::{mode}::{prompt.strip()[-40:]}"


def _make_inputs(work: Path, n: int):
    queries = []
    for i in range(n):
        queries.append({
            "query_id": f"q{i}", "pair_id": f"p{i}", "fact_id": f"f{i}",
            "audit_id": f"a{i}", "group": "KB_Member", "claim_type": "true",
            "query": f"statement number {i} to verify uniquely {i}",
            "expected_entity": "x", "original_entity": "x", "counterfactual_entity": None,
            "entity_type": "TERM", "accepted": True,
        })
    qp = work / "q.jsonl"
    bp = work / "b.jsonl"
    write_jsonl(queries, qp)
    write_jsonl([{"audit_id": q["audit_id"], "doc_id": "d"} for q in queries], bp)
    return qp, bp


def _run(work, qp, bp, client, *, workers, rpm, tag):
    rag_out = work / f"rag_{tag}.jsonl"
    llm_out = work / f"llm_{tag}.jsonl"
    with patch("src.rag.runner.RagRetriever", _FakeRetriever):
        run_rag_and_llm_only(
            dataset="edgar", queries_path=qp, benchmark_path=bp, index_dir=work / "idx",
            rag_output_path=rag_out, llm_output_path=llm_out, client=client,
            resume=False, force=True, max_workers=workers, requests_per_minute=rpm,
        )
    rag = {r["query_id"]: r["response"] for r in read_jsonl(rag_out)}
    llm = {r["query_id"]: r["response"] for r in read_jsonl(llm_out)}
    return rag, llm


class TokenBucketTest(unittest.TestCase):
    def test_rate_never_exceeds_rpm_under_concurrency(self) -> None:
        """多线程抢令牌,任意时刻累计发放数不超过 起步1枚+匀速补充(速率≤RPM)。"""
        rpm = 600.0
        interval = 60.0 / rpm
        n, threads = 30, 5
        tb = TokenBucket(rpm)
        stamps: list[float] = []
        lock = threading.Lock()
        counter = [0]

        def worker():
            while True:
                with lock:
                    if counter[0] >= n:
                        return
                    counter[0] += 1
                tb.acquire()
                with lock:
                    stamps.append(time.monotonic())

        ths = [threading.Thread(target=worker) for _ in range(threads)]
        [t.start() for t in ths]
        [t.join() for t in ths]

        stamps.sort()
        # 核心不变式:第 i 枚发放时刻,已发放数 i+1 ≤ 1 + 经过时间/间隔 (+1 容差防抖动)。
        worst_excess = max((i + 1) - (1 + (ts - stamps[0]) / interval) for i, ts in enumerate(stamps))
        self.assertLessEqual(worst_excess, 1.5, "瞬时发放超过 RPM 上限")


class ConcurrentRunnerTest(unittest.TestCase):
    def test_concurrent_output_equals_serial(self) -> None:
        """workers=4(+令牌桶) 与 workers=1 的 RAG/LLM 输出逐条一致(并发不打乱/丢/重)。"""
        with temporary_dir() as work:
            qp, bp = _make_inputs(work, 12)
            # 高 rpm 让令牌桶几乎不拖慢,专测并发正确性。
            serial = _run(work, qp, bp, _DetClient(), workers=1, rpm=0, tag="s")
            concur = _run(work, qp, bp, _DetClient(), workers=4, rpm=6000, tag="c")
            self.assertEqual(serial[0], concur[0], "RAG 输出并发与串行不一致")
            self.assertEqual(serial[1], concur[1], "LLM 输出并发与串行不一致")
            self.assertEqual(len(serial[0]), 12)
            self.assertEqual(len(serial[1]), 12)

    def test_concurrency_absorbs_slow_calls(self) -> None:
        """每条 call 变慢时,workers=4 墙钟显著短于 workers=1(并发填满管道抗卡顿)。"""
        with temporary_dir() as work:
            qp, bp = _make_inputs(work, 8)
            t0 = time.monotonic()
            _run(work, qp, bp, _DetClient(per_call_sleep=0.05), workers=1, rpm=0, tag="slow1")
            serial_t = time.monotonic() - t0

            t0 = time.monotonic()
            _run(work, qp, bp, _DetClient(per_call_sleep=0.05), workers=4, rpm=0, tag="slow4")
            concur_t = time.monotonic() - t0

            # 8 query × 2 call × 0.05s:串行 ~0.8s,4 并发 ~0.2s。留足裕度,只断言明显更快。
            self.assertLess(concur_t, serial_t * 0.6, f"并发未有效抗卡顿: serial={serial_t:.2f} concur={concur_t:.2f}")


if __name__ == "__main__":
    unittest.main()
