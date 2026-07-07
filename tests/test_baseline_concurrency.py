"""Baseline 令牌桶 + 并发抗卡顿测试(第 12 步提速安全性保证)。

中文说明
========
第 12 步 baseline 复现接上了「全局令牌桶 + 跨目标并发」(复用第 10 步 runner 的 TokenBucket)。
本测试用【可控 fake 替身】(确定性 victim/attacker/检索,不联网、不加载 gpt2)证明三件事:

  1) 并发不改结果:workers=4(令牌桶开) 与 workers=1(串行) 对每个 doc_id 打出的分【逐个相同】。
     覆盖 RAG-MIA / S2MIA / DCMI / IA(IA/DCMI 还额外走 attacker 令牌桶与 embedder 并发)。
  2) MBA 无状态串味:旧实现把 mask_answers 存在共享单例上,get_attack_query→(慢victim)→
     get_mia_score 之间被别的目标覆盖会算错分。用 barrier 强制两个目标在「取到答案后、打分前」
     同时挂起,证明新实现(局部 mask_answers)下各目标仍打对自己的分(旧实现此处必错)。
  3) 令牌桶真限速:接了桶后,victim 调用的实际速率被压到 ≤ RPM(证明 acquire 确实生效)。

这些都不触碰「测量仪器」——每条仍单发、同 prompt,只验证并发调度与限速本身不改读数。
"""

from __future__ import annotations

import hashlib
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from src.baselines import victim_harness as vh
from src.baselines.MBA.mba_highdiff import MBAHighDiff
from src.baselines.victim_harness import BASELINES, Services, run_one_baseline
from src.rag.runner import TokenBucket
from src.utils.io import read_jsonl


# ============================================================
# 可控 fake 替身(鸭子类型,只实现被用到的方法;全部确定性)
# ============================================================
class _FakeEmbedder:
    """确定性 2 维嵌入:仅供 IA 的 cosine 区分度筛选用,输入相同→输出相同。"""

    def encode(self, texts: list[str]) -> np.ndarray:
        out = []
        for t in texts:
            s = sum(ord(c) for c in t)
            out.append([float(s % 97) + 1.0, float(len(t) % 13) + 1.0])
        return np.asarray(out, dtype="float32")


class _FakeRetriever:
    """空检索(上下文恒为空,prompt 只随 query 变),携带确定性 embedder。"""

    def __init__(self) -> None:
        self.embedder = _FakeEmbedder()

    def retrieve(self, query: str, top_k: int = 5):
        return []


class _DetVictim:
    """确定性 victim:回答只由 prompt 决定(哈希),因此每个目标的分是纯函数、与执行顺序无关。

    记录每次调用时刻,供限速测试统计实际速率。
    """

    def __init__(self) -> None:
        self.stamps: list[float] = []
        self.lock = threading.Lock()

    def generate(self, prompt: str, temperature: float = 0.0, timeout: float = 60.0, max_tokens: int = 512) -> str:
        with self.lock:
            self.stamps.append(time.monotonic())
        h = hashlib.sha1(prompt.encode("utf-8")).hexdigest()
        yn = "Yes" if int(h[0], 16) % 2 == 0 else "No"  # RAG-MIA/IA 的 yes/no 解析用
        return f"{yn}. deterministic reply {h[:16]}"     # S2/DCMI 的 BLEU 也确定


def _det_attacker(prompt: str) -> str:
    """确定性 attacker(IA/DCMI 用):按 prompt 类型返回固定内容,不随机、不联网。"""
    h = hashlib.sha1(("ATK::" + prompt).encode("utf-8")).hexdigest()
    if "yes/no questions" in prompt:                       # IA 生成问题
        return "\n".join(f"{i}. Is aspect {h[i]} present in the record?" for i in range(1, 9))
    if "Replace" in prompt and "antonyms" in prompt:       # DCMI 反义词扰动
        return "Perturbed calibration variant " + h[:24]
    return "Yes" if int(h[0], 16) % 2 == 0 else ("topic noun phrase " + h[:8])  # summary / IA 答案


_TARGETS = [
    {"doc_id": f"doc{i}", "group": "KB_Member" if i % 2 == 0 else "True_Non_Member",
     "text": f"Sample record number {i} about entity E{i} located in city C{i} reporting value {i * 7}.",
     "source_id": f"src{i % 3}"}
    for i in range(12)
]


def _scores(path: Path) -> dict[str, float | None]:
    return {r["doc_id"]: r["score"] for r in read_jsonl(path)}


class ConcurrencyEquivalenceTests(unittest.TestCase):
    """workers=4(令牌桶开) 与 workers=1(串行) 的每目标打分必须逐个一致。"""

    def _run(self, method: str, workers: int, rpm: float, out: Path) -> dict[str, float | None]:
        attacker = _det_attacker if BASELINES[method].needs_attacker else None
        bucket = TokenBucket(rpm) if rpm > 0 else None
        svc = Services(
            retriever=_FakeRetriever(), victim=_DetVictim(), attacker_chat=attacker,
            top_k=3, victim_bucket=bucket, attacker_bucket=bucket,  # 同 key → 共桶
        )
        run_one_baseline(method, _TARGETS, svc, output_path=out, resume=False, force=True, max_workers=workers)
        return _scores(out)

    def test_concurrent_scores_equal_serial(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            for method in ("RAG-MIA", "S2MIA", "DCMI", "IA"):
                serial = self._run(method, workers=1, rpm=0.0, out=tmp / f"{method}_s.jsonl")
                # rpm 设高(6000=100/s),令牌桶几乎不拖慢测试,但仍真正走 acquire 路径。
                concur = self._run(method, workers=4, rpm=6000.0, out=tmp / f"{method}_c.jsonl")
                self.assertEqual(len(serial), len(_TARGETS), f"{method}: 目标数不符")
                self.assertEqual(serial, concur, f"{method}: 并发与串行打分不一致(并发污染了结果)")


class MbaConcurrencyStateTests(unittest.TestCase):
    """MBA 的 mask_answers 必须是线程局部的(旧共享单例实现会在并发下串味)。"""

    def test_mba_concurrent_no_state_corruption(self) -> None:
        # 假 MBA 单例:不加载 gpt2。build_query 让「答案=该目标自己的文本」;打分走真实静态方法。
        class _FakeMBA:
            document_slice_size = 4096
            num_masks = 1

            def build_query(self, text: str):
                return f"FILL::{text}", {1: [text]}

        orig = vh._get_mba_singleton
        vh._get_mba_singleton = lambda: _FakeMBA()

        # barrier 逼两个目标在「victim 返回答案的瞬间」同时挂起——正是旧实现 get_attack_query 会
        # 覆盖共享 self.mask_answers 的窗口。新实现各持局部 mask_answers,应各打对自己的分。
        barrier = threading.Barrier(2, timeout=10)

        class _BarrierVictim:
            def generate(self, prompt: str, **kw) -> str:
                text = prompt.split("FILL::", 1)[1].split("\nAnswer:", 1)[0]
                barrier.wait()  # 两个目标在此会合(都已取到各自答案,尚未打分)
                return f"[MASK_1]: {text}"  # 回填「自己那条目标的文本」→ 填对率应为 1.0

        try:
            with tempfile.TemporaryDirectory() as d:
                out = Path(d) / "mba.jsonl"
                svc = Services(retriever=_FakeRetriever(), victim=_BarrierVictim(), top_k=1)
                targets = [
                    {"doc_id": "d1", "group": "KB_Member", "text": "alpha", "source_id": "s1"},
                    {"doc_id": "d2", "group": "True_Non_Member", "text": "beta", "source_id": "s2"},
                ]
                run_one_baseline("MBA", targets, svc, output_path=out, resume=False, max_workers=2)
                scores = _scores(out)
                # 各目标 victim 回填的是「自己」的文本 → 两条都应 1.0。
                # 旧共享单例实现下,barrier 交错会让两条读到对方的 mask_answers → 至少一条变 0.0。
                self.assertEqual(scores, {"d1": 1.0, "d2": 1.0})
        finally:
            vh._get_mba_singleton = orig


class RateLimitTests(unittest.TestCase):
    """令牌桶接进 rag_answer 后,victim 实际调用速率被压到 ≤ RPM。"""

    def test_token_bucket_bounds_victim_rate(self) -> None:
        rpm = 240.0  # 4 次/秒 → 12 次至少 ~2.75s
        vic = _DetVictim()
        svc = Services(retriever=_FakeRetriever(), victim=vic, victim_bucket=TokenBucket(rpm), top_k=1)
        with tempfile.TemporaryDirectory() as d:
            run_one_baseline("RAG-MIA", _TARGETS, svc, output_path=Path(d) / "rate.jsonl",
                             resume=False, max_workers=6)
        stamps = sorted(vic.stamps)
        self.assertEqual(len(stamps), len(_TARGETS))
        elapsed = stamps[-1] - stamps[0]
        min_expected = (len(stamps) - 1) / (rpm / 60.0)  # 12 次 → 11 个间隔 × 0.25s = 2.75s
        # 允许 20% 宽容(调度抖动),但必须证明确实被限速(不是一拥而上)。
        self.assertGreaterEqual(elapsed, min_expected * 0.8,
                                f"victim 速率未被令牌桶限制:{len(stamps)} 次仅用 {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
