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
import copy
import importlib.util
import io
import os
import sys
import tempfile
from contextlib import ExitStack, contextmanager, redirect_stdout
from pathlib import Path
from typing import Any, Iterator
import unittest
from unittest.mock import patch
import uuid

from src.rag.runner import (
    TokenBucket, _call_generator, build_rag_prompt, run_rag_and_llm_only,
    run_v24_formal_cell, validate_fixed_query_budget,
)
from src.utils.hash import sha256_file, sha256_obj, sha256_text
from src.utils.io import load_yaml, read_json, read_jsonl, write_json, write_jsonl


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
            "source_key": f"s{i}",
            "query": f"statement number {i} to verify uniquely {i}",
            "expected_entity": "x", "original_entity": "x", "counterfactual_entity": None,
            "entity_type": "TERM", "accepted": True,
        })
    qp = work / "q.jsonl"
    bp = work / "b.jsonl"
    write_jsonl(queries, qp)
    write_jsonl([{"audit_id": q["audit_id"], "doc_id": "d"} for q in queries], bp)
    return qp, bp


def _run(work, qp, bp, client, *, workers, rpm, tag, variant_id="full_pvs"):
    rag_out = work / f"rag_{tag}.jsonl"
    llm_out = work / f"llm_{tag}.jsonl"
    with patch("src.rag.runner.RagRetriever", _FakeRetriever):
        run_rag_and_llm_only(
            dataset="edgar", queries_path=qp, benchmark_path=bp, index_dir=work / "idx",
            rag_output_path=rag_out, llm_output_path=llm_out, client=client,
            resume=False, force=True, max_workers=workers, requests_per_minute=rpm,
            run_llm_only=True,
            variant_id=variant_id,
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
    def test_checkpoint_every_one_persists_each_llm_only_response(self) -> None:
        with temporary_dir() as work:
            qp, bp = _make_inputs(work, 3)
            rag_out = work / "rag_should_not_exist.jsonl"
            llm_out = work / "llm_checkpointed.jsonl"
            write_batches: list[int] = []

            from src.rag import runner

            real_write_jsonl = runner.write_jsonl

            def recording_write_jsonl(
                rows: list[dict[str, Any]],
                path: str | Path,
                *,
                append: bool = False,
            ) -> None:
                if Path(path) == llm_out:
                    write_batches.append(len(rows))
                return real_write_jsonl(rows, path, append=append)

            with patch("src.rag.runner.write_jsonl", side_effect=recording_write_jsonl):
                run_rag_and_llm_only(
                    dataset="edgar",
                    queries_path=qp,
                    benchmark_path=bp,
                    index_dir=work / "idx",
                    rag_output_path=rag_out,
                    llm_output_path=llm_out,
                    client=_DetClient(),
                    resume=False,
                    force=True,
                    run_rag=False,
                    run_llm_only=True,
                    checkpoint_every=1,
                )

            self.assertEqual(write_batches, [1, 1, 1])
            self.assertEqual(len(list(read_jsonl(llm_out))), 3)

    def test_checkpoint_every_must_be_positive(self) -> None:
        with temporary_dir() as work:
            qp, bp = _make_inputs(work, 1)
            with self.assertRaisesRegex(ValueError, "checkpoint_every"):
                run_rag_and_llm_only(
                    dataset="edgar",
                    queries_path=qp,
                    benchmark_path=bp,
                    index_dir=work / "idx",
                    rag_output_path=work / "rag.jsonl",
                    llm_output_path=work / "llm.jsonl",
                    client=_DetClient(),
                    run_rag=False,
                    run_llm_only=True,
                    checkpoint_every=0,
                )

    def test_llm_only_collection_does_not_load_retriever_or_touch_rag_output(self) -> None:
        with temporary_dir() as work:
            qp, bp = _make_inputs(work, 2)
            rag_out = work / "rag_should_not_exist.jsonl"
            llm_out = work / "llm_only.jsonl"
            with patch(
                "src.rag.runner.RagRetriever",
                side_effect=AssertionError("matched-control must not load the retriever"),
            ):
                manifest = run_rag_and_llm_only(
                    dataset="edgar",
                    queries_path=qp,
                    benchmark_path=bp,
                    index_dir=work / "idx",
                    rag_output_path=rag_out,
                    llm_output_path=llm_out,
                    client=_DetClient(),
                    resume=False,
                    force=True,
                    run_rag=False,
                    run_llm_only=True,
                )
            self.assertFalse(rag_out.exists())
            self.assertFalse(rag_out.with_suffix(".manifest.json").exists())
            self.assertEqual(len(list(read_jsonl(llm_out))), 2)
            self.assertFalse(manifest["run_rag"])
            self.assertEqual(manifest["llm_only_integrity"]["missing"], 0)

    def test_variant_provenance_is_written_to_rows_and_manifest(self) -> None:
        with temporary_dir() as work:
            qp, bp = _make_inputs(work, 1)
            rag_out = work / "rag_control.jsonl"
            llm_out = work / "llm_control.jsonl"
            with patch("src.rag.runner.RagRetriever", _FakeRetriever):
                manifest = run_rag_and_llm_only(
                    dataset="edgar",
                    queries_path=qp,
                    benchmark_path=bp,
                    index_dir=work / "idx",
                    rag_output_path=rag_out,
                    llm_output_path=llm_out,
                    client=_DetClient(),
                    resume=False,
                    force=True,
                    variant_id="random_same_type_counterfactual",
                )
            row = next(read_jsonl(rag_out))
            self.assertEqual(row["variant_id"], "random_same_type_counterfactual")
            self.assertEqual(manifest["variant_id"], "random_same_type_counterfactual")
            self.assertEqual(manifest["query_budget"], 1)
            self.assertTrue(manifest["queries_hash"])
            self.assertTrue(manifest["source_whitelist_hash"])

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
            # 让模拟端点延迟稳定高于 Windows manifest/hash 文件 I/O 抖动。
            _run(work, qp, bp, _DetClient(per_call_sleep=0.1), workers=1, rpm=0, tag="slow1")
            serial_t = time.monotonic() - t0

            t0 = time.monotonic()
            _run(work, qp, bp, _DetClient(per_call_sleep=0.1), workers=4, rpm=0, tag="slow4")
            concur_t = time.monotonic() - t0

            # 8 query × 2 call × 0.1s：串行约 1.6s，4 并发约 0.4s。
            self.assertLess(concur_t, serial_t * 0.6, f"并发未有效抗卡顿: serial={serial_t:.2f} concur={concur_t:.2f}")


class RetryUntilSuccessTest(unittest.TestCase):
    def test_generator_retries_across_cooldown_cycles_until_success(self) -> None:
        class _FlakyClient:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, prompt: str, **kw) -> str:
                self.calls += 1
                if self.calls < 5:
                    raise TimeoutError("The read operation timed out")
                return "ok"

        client = _FlakyClient()
        response, error = _call_generator(
            client, "prompt", temperature=0.0, timeout=1.0, max_tokens=8,
            retries=1, retry_backoff_base=0, retry_backoff_max=0,
            retry_until_success=True, retry_cooldown_seconds=0,
        )
        self.assertEqual(client.calls, 5)
        self.assertEqual(response, "ok")
        self.assertIsNone(error)

    def test_non_api_error_is_returned_without_infinite_retry(self) -> None:
        class _BrokenClient:
            def generate(self, prompt: str, **kw) -> str:
                raise ValueError("invalid local payload")

        response, error = _call_generator(
            _BrokenClient(), "prompt", temperature=0.0, timeout=1.0, max_tokens=8,
            retries=0, retry_backoff_base=0, retry_backoff_max=0,
            retry_until_success=True, retry_cooldown_seconds=0,
        )
        self.assertEqual(response, "")
        self.assertIn("invalid local payload", error or "")


class V24FormalRunnerTests(unittest.TestCase):
    """保留真实 split/预算/运行循环/评分，只替换外部模型、检索与 Git 环境。"""

    root = Path(__file__).resolve().parents[1]
    validation_report: dict[str, Any] = {}

    @classmethod
    def setUpClass(cls) -> None:
        from src.prepare.restoration_first_v24 import select_luna_direct_pairs

        cls.selected, cls.split_rows, cls.docstore = [], [], []
        for index in range(2250):
            key = f"nfcorpus::synthetic-{index}"
            text = f"The Atlas-{index} trial enrolled 43 RA patients."
            source = {"dataset": "nfcorpus", "source_key": key, "chunk_sha256": sha256_text(text),
                      "chunk_text": text, "input_kind": "development_fixture"}
            result = select_luna_direct_pairs(source, [{
                "true_claim": text, "original_entity": "43 RA patients",
                "q_plus": f"Did the Atlas-{index} trial enroll 43 RA patients?",
                "counter_entities": ["44 RA patients", "45 RA patients", "46 RA patients"],
            }])
            cls.selected.extend(result["selected_pairs"])
            group = "KB_Member" if index < 1000 else "True_Non_Member" if index < 2000 else "Reserve"
            cls.split_rows.append({
                "dataset": "nfcorpus", "split_index": index, "group": group, "source_key": key,
                "source_hash": source["chunk_sha256"],
                "ordered_pair_ids": [pair["pair_id"] for pair in result["selected_pairs"]],
                "source_integrity_hash": sha256_obj(result["selected_pairs"]),
            })
            if group == "KB_Member":
                cls.docstore.append({
                    "dataset": "nfcorpus", "group": group, "source_key": key,
                    "doc_id": f"synthetic-{index}", "chunk_id": f"synthetic-{index}_c00",
                    "text": text, "text_hash": sha256_text(text),
                    "metadata": {"source_key": key, "source_text_hash": source["chunk_sha256"]},
                })

    def setUp(self) -> None:
        WORKSPACE_TMP.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="tb_v24_", dir=WORKSPACE_TMP)
        self.work = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.config = load_yaml(self.root / "configs/restoration_first_v24.yaml")
        self.config_path = self.work / "runtime.yaml"
        self.split = {"kind": "pcv_v24_split_manifest", "protocol_version": "pcv-mia-v24",
                      "dataset": "nfcorpus", "selection_seed": 42, "rows": copy.deepcopy(self.split_rows)}
        self._write_split()
        write_jsonl(self.selected, self.work / "pairs.jsonl")
        self.index = self.work / "index"
        self.index.mkdir()
        write_jsonl(self.docstore, self.index / "docstore.jsonl")
        write_json({"synthetic_index": True}, self.index / "index.json")
        self.manifest = {
            "dataset": "nfcorpus", "retriever_backend": "dense", "retriever_id": "synthetic-embedding",
            "embedding_revision": "synthetic-revision", "embedding_local_files_only": True,
            "security_boundary": {"allowed_groups": ["KB_Member"], "is_shadow_index": False},
            "index_filename": "index.json", "index_hash": sha256_file(self.index / "index.json"),
        }
        self.profile = {
            "profile_name": "synthetic", "provider": "openai_compatible", "model": "synthetic-victim",
            "model_version": "synthetic-v1", "base_url": "http://invalid.local/v1", "api_key_env": "UNUSED",
            "system_prompt": "", "timeout": 1.0, "max_tokens": 64,
        }
        write_json({"victim": {"profiles": {"synthetic": self.profile}}}, self.work / "profiles.yaml")
        self.runtime = {
            "selected_pairs_path": str(self.work / "pairs.jsonl"), "split_manifest_path": str(self.work / "split.json"),
            "output_dir": str(self.work / "run"), "llm_profiles_path": str(self.work / "profiles.yaml"),
            "victim_profile": "synthetic", "generator_family": "gpt", "concrete_model": "synthetic-victim",
            "generator_version": "synthetic-v1",
            "retrieval": {"backend": "dense", "retriever_id": "synthetic-embedding", "index_dir": str(self.index), "top_k": 1},
            "generation": {
                "temperature": 0.0, "max_tokens": 64, "timeout": 1.0, "retries": 0,
                "retry_backoff_base": 0, "retry_backoff_max": 0, "retry_until_success": False,
                "retry_cooldown_seconds": 0, "request_interval_seconds": 0,
                "max_workers": 1, "requests_per_minute": 0, "checkpoint_every": 6,
            },
        }
        self.config["formal"]["runtime"] = self.runtime
        self._write_index()
        self.environment = patch.dict(os.environ, {key: "" for key in (
            "PCV_VICTIM_PROFILE", "PCV_VICTIM_MODEL", "PCV_VICTIM_MODEL_VERSION", "PCV_VICTIM_BASE_URL",
        )})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def _write_split(self) -> None:
        self.split.pop("manifest_sha256", None)
        self.split["manifest_sha256"] = sha256_obj(self.split)
        write_json(self.split, self.work / "split.json")

    def _write_config(self) -> None:
        write_json(self.config, self.config_path)

    def _write_index(self) -> None:
        self.manifest["docstore_hash"] = sha256_file(self.index / "docstore.jsonl")
        write_json(self.manifest, self.index / "index_manifest.json")
        self.runtime["retrieval"]["index_manifest_sha256"] = sha256_file(self.index / "index_manifest.json")
        self._write_config()

    def _run(self, **kwargs: Any) -> dict[str, Any]:
        return run_v24_formal_cell(dataset="nfcorpus", config_path=self.config_path, project_root=self.root, **kwargs)

    @contextmanager
    def _dependencies(self, *, interrupt_after: int | None = None) -> Iterator[dict[str, Any]]:
        from src.rag.retriever import RetrievedChunk

        counters = {"client_calls": 0, "retriever_calls": 0, "nli_calls": 0, "prompts": []}
        test = self

        class Client:
            def generate_with_metadata(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
                counters["client_calls"] += 1
                counters["prompts"].append(prompt)
                question = prompt.split("Verification request:\n", 1)[1].split("\n\n", 1)[0]
                test.assertEqual(prompt, build_rag_prompt(question, [test.docstore[0]["text"]]))
                test.assertNotIn("KB_Member", prompt)
                test.assertNotIn("True_Non_Member", prompt)
                response = "Consistent"
                if "44 RA patients" in question:
                    response = "Inconsistent: 43 RA patients"
                elif "45 RA patients" in question:
                    response = "Inconsistent: forty-three participants with rheumatoid arthritis"
                return {"content": response, "provider_model_id": "synthetic-victim",
                        "system_fingerprint": "synthetic-fp", "provider_request_id": str(counters["client_calls"]),
                        "input_tokens": 7, "output_tokens": 3, "latency_ms": 0, "finish_reason": "stop"}

        class Retriever:
            retriever_backend = "dense"

            def __init__(self, index_dir: Path) -> None:
                self.manifest = read_json(index_dir / "index_manifest.json")
                self.retriever_backend = self.manifest["retriever_backend"]

            def retrieve(self, query: str, top_k: int) -> list[Any]:
                if interrupt_after is not None and counters["client_calls"] == interrupt_after:
                    raise RuntimeError("synthetic interruption")
                counters["retriever_calls"] += 1
                row = test.docstore[0]
                return [RetrievedChunk(row["chunk_id"], row["doc_id"], row["text"], 1.0, row["metadata"])]

        class Nli:
            def probabilities(self, pairs: list[tuple[str, str]]) -> list[dict[str, float]]:
                counters["nli_calls"] += 1
                test.assertEqual(pairs, [
                    ("The corrected value is forty-three participants with rheumatoid arthritis.",
                     "The corrected value is 43 RA patients."),
                    ("The corrected value is 43 RA patients.",
                     "The corrected value is forty-three participants with rheumatoid arthritis."),
                ])
                return [{"entailment": value, "neutral": 1.0 - value, "contradiction": 0.0} for value in (0.9, 0.8)]

        with ExitStack() as stack:
            counters["nli_factory"] = stack.enter_context(patch("src.scoring.pcv_scorer.build_hybrid_pvs_nli", return_value=Nli()))
            counters["client_factory"] = stack.enter_context(patch("src.llm.factory.build_victim_client", return_value=(Client(), self.profile)))
            counters["retriever_factory"] = stack.enter_context(patch("src.rag.runner.RagRetriever", side_effect=Retriever))
            stack.enter_context(patch("src.rag.runner.git_snapshot", return_value={"commit": "a" * 40, "dirty": False, "branch": "synthetic"}))
            stack.enter_context(patch("src.rag.runner.tqdm", side_effect=lambda rows, **_: rows))
            yield counters

    def test_cli_full_split_end_to_end_resume_and_source_scores(self) -> None:
        started = time.perf_counter()
        spec = importlib.util.spec_from_file_location("v24_formal_cli_test", self.root / "scripts/10_run_rag_and_llm_only.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        argv = ["run", "--v24", "--dataset", "nfcorpus", "--config", str(self.config_path)]
        with self._dependencies(interrupt_after=6) as first:
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
                    cli.main()
        self.assertEqual(first["client_calls"], 6)
        output = self.work / "run"
        self.assertEqual(len(list(read_jsonl(output / "rag_responses.jsonl"))), 6)
        self.assertFalse((output / "scores").exists())
        with self._dependencies() as rest:
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(), 0)
        self.assertEqual(rest["client_calls"], 11994)
        self.assertEqual(rest["nli_calls"], 2000)
        rest["nli_factory"].assert_called_once()
        summary = read_json(output / "run_summary.json")
        queries = list(read_jsonl(output / "query_plan.jsonl"))
        responses = list(read_jsonl(output / "rag_responses.jsonl"))
        sources = list(read_jsonl(output / "scores/source_scores.jsonl"))
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["split"]["source_count"], 2250)
        self.assertEqual(summary["split"]["group_counts"], {"KB_Member": 1000, "True_Non_Member": 1000, "Reserve": 250})
        self.assertEqual(summary["scored_source_count"], 2000)
        self.assertEqual(summary["scored_pair_count"], 6000)
        self.assertEqual(len(queries), 12000)
        self.assertEqual(len({row["query_id"] for row in responses}), 12000)
        self.assertEqual({row["group"] for row in responses}, {"KB_Member", "True_Non_Member"})
        self.assertFalse((output / "unused_llm_only.jsonl").exists())
        self.assertEqual(len({row["query"] for row in queries[:6] if row["claim_type"] == "true"}), 1)
        self.assertEqual([row["query"] for row in queries[:6:2]], [self.selected[0]["q_plus_text"]] * 3)
        self.assertEqual([row["query"] for row in queries[1:6:2]], [pair["q_minus_text"] for pair in self.selected[:3]])
        for source in sources:
            self.assertAlmostEqual(source["source_pvs_mean"], 0.8 / 3.0)
            self.assertEqual(source["source_pvs"], source["source_pvs_mean"])
            self.assertEqual(source["source_pvs_median"], 0.8)
            self.assertEqual([pair["pair_pvs"] for pair in source["pair_scores"]], [1.0, 0.8, -1.0])
        scoring = read_json(output / "scores/scoring_summary.json")
        self.assertEqual(scoring["run_kind"], "v24_formal_hybrid_pvs")
        before = sha256_file(output / "run_summary.json")
        with self._dependencies() as done:
            resumed = self._run()
        self.assertTrue(resumed["resumed_completed"])
        for name in ("client_factory", "retriever_factory", "nli_factory"):
            done[name].assert_not_called()
        self.assertEqual(sha256_file(output / "run_summary.json"), before)
        with (output / "scores/source_scores.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        with self._dependencies() as altered, self.assertRaisesRegex(ValueError, "resume_artifact_drift"):
            self._run()
        altered["client_factory"].assert_not_called()
        altered["nli_factory"].assert_not_called()
        type(self).validation_report = {
            "kind": "synthetic_mock_only", "split_sources": 2250, "index_member_sources": 1000,
            "scored_sources": 2000, "reserve_queries": 0, "pair_scores": 6000,
            "unique_queries": 12000, "mock_victim_calls": first["client_calls"] + rest["client_calls"],
            "mock_retriever_calls": first["retriever_calls"] + rest["retriever_calls"], "mock_nli_calls": rest["nli_calls"],
            "before_interrupt_calls": 6, "resume_calls": rest["client_calls"], "completed_resume_calls": 0,
            "sample_pair_pvs": [1.0, 0.8, -1.0], "sample_source_mean": 0.8 / 3.0, "sample_source_median": 0.8,
            "external_api_calls": 0, "gpu_model_loads": 0, "wall_seconds": round(time.perf_counter() - started, 3),
        }

    def test_read_only_preflight_does_not_initialize_any_external_runtime(self) -> None:
        with self._dependencies() as calls:
            result = self._run(dry_run=True)
        self.assertEqual(result["status"], "prepared_inputs_only")
        self.assertEqual(result["planned_victim_queries"], 12000)
        for name in ("client_factory", "retriever_factory", "nli_factory"):
            calls[name].assert_not_called()
        self.assertFalse((self.work / "run").exists())

    def test_shared_positive_is_explicit_and_duplicate_counter_queries_still_fail(self) -> None:
        from src.prepare.restoration_first_v24 import build_luna_direct_run_plan

        plan = build_luna_direct_run_plan(self.selected, self.split, dataset="nfcorpus")
        rows = plan["queries"][:6]
        with self.assertRaisesRegex(RuntimeError, "duplicate_query_text"):
            validate_fixed_query_budget(rows, 3)
        self.assertEqual(validate_fixed_query_budget(rows, 3, allow_shared_q_plus=True)["planned_queries"], 6)
        for altered in (rows[:4], rows + [rows[0]], [*rows[:5], {**rows[5], "query": rows[1]["query"]}]):
            with self.assertRaises(RuntimeError):
                validate_fixed_query_budget(altered, 3, allow_shared_q_plus=True)

    def test_source_pair_and_query_drift_fail_before_model_loading(self) -> None:
        variants = ("missing_source", "missing_pair", "q_minus", "q_plus", "source_hash", "pair_order", "split_overlap")
        for variant in variants:
            with self.subTest(variant=variant):
                pairs = copy.deepcopy(self.selected)
                self.split["rows"] = copy.deepcopy(self.split_rows)
                if variant == "missing_source":
                    pairs = pairs[3:]
                elif variant == "missing_pair":
                    pairs = pairs[1:]
                elif variant == "q_minus":
                    pairs[0]["q_minus_text"] = "Changed counterfactual?"
                elif variant == "q_plus":
                    pairs[0]["q_plus_text"] = "Changed factual question?"
                elif variant == "source_hash":
                    self.split["rows"][0]["source_hash"] = "f" * 64
                elif variant == "pair_order":
                    self.split["rows"][0]["ordered_pair_ids"].reverse()
                else:
                    self.split["rows"][1]["source_key"] = self.split["rows"][0]["source_key"]
                write_jsonl(pairs, self.work / "pairs.jsonl")
                self._write_split()
                with self._dependencies() as calls, self.assertRaises(ValueError):
                    self._run()
                calls["client_factory"].assert_not_called()
                calls["nli_factory"].assert_not_called()

    def test_index_rejects_nonmember_reserve_wrong_source_and_missing_members(self) -> None:
        for variant in ("nonmember", "reserve", "wrong_hash", "missing_member", "bad_text"):
            with self.subTest(variant=variant):
                rows = copy.deepcopy(self.docstore)
                if variant in {"nonmember", "reserve"}:
                    source = self.split_rows[1000 if variant == "nonmember" else 2000]
                    rows[0].update(source_key=source["source_key"], group=source["group"])
                    rows[0]["metadata"].update(source_key=source["source_key"], source_text_hash=source["source_hash"])
                elif variant == "wrong_hash":
                    rows[0]["metadata"]["source_text_hash"] = "f" * 64
                elif variant == "missing_member":
                    rows.pop()
                else:
                    rows[0]["text"] = "Changed text"
                write_jsonl(rows, self.index / "docstore.jsonl")
                self._write_index()
                with self._dependencies() as calls, self.assertRaisesRegex(ValueError, "v24_index_"):
                    self._run()
                calls["client_factory"].assert_not_called()
                calls["nli_factory"].assert_not_called()

    def test_fixed_split_size_and_model_or_backend_drift_fail_closed(self) -> None:
        for variant in ("budget", "model", "backend", "index_hash"):
            with self.subTest(variant=variant):
                baseline = copy.deepcopy(self.config)
                if variant == "budget":
                    self.config["formal"]["queries_per_source"] = 8
                elif variant == "model":
                    self.runtime["concrete_model"] = "wrong-model"
                elif variant == "backend":
                    self.runtime["retrieval"]["backend"] = "bm25"
                else:
                    self.runtime["retrieval"]["index_manifest_sha256"] = "f" * 64
                self._write_config()
                with self._dependencies() as calls, self.assertRaisesRegex(ValueError, "v24_"):
                    self._run()
                calls["client_factory"].assert_not_called()
                self.config = baseline
                self.runtime = self.config["formal"]["runtime"]
        self.split["rows"].pop()
        self._write_split()
        self._write_config()
        with self._dependencies(), self.assertRaisesRegex(ValueError, "v24_split_row_count"):
            self._run()

    def test_missing_nli_stops_before_any_victim_or_retriever_initialization(self) -> None:
        with self._dependencies() as calls:
            calls["nli_factory"].side_effect = FileNotFoundError("synthetic missing weights")
            with self.assertRaises(FileNotFoundError):
                self._run()
        calls["client_factory"].assert_not_called()
        calls["retriever_factory"].assert_not_called()
        self.assertFalse((self.work / "run").exists())

    def test_bm25_and_hybrid_preflight_bind_their_own_indexes(self) -> None:
        sparse_dir = self.work / "sparse"
        sparse_dir.mkdir()
        write_jsonl(self.docstore, sparse_dir / "docstore.jsonl")
        write_json({"synthetic_index": True}, sparse_dir / "index.json")
        sparse_manifest = {**self.manifest, "retriever_backend": "bm25", "retriever_id": "bm25"}
        write_json(sparse_manifest, sparse_dir / "index_manifest.json")
        sparse_hash = sha256_file(sparse_dir / "index_manifest.json")
        self.runtime["retrieval"].update(
            backend="hybrid", retriever_id="synthetic-embedding+bm25+rrf+bge-reranker",
            bm25_index_dir=str(sparse_dir), bm25_index_manifest_sha256=sparse_hash,
            hybrid={"dense_candidate_top_k": 20, "bm25_candidate_top_k": 20, "rrf_k": 60,
                    "fusion_top_k": 20, "final_top_k": 1, "reranker_model": "BAAI/bge-reranker-base",
                    "reranker_revision": "synthetic-reranker", "reranker_local_files_only": True},
        )
        self._write_config()
        with self._dependencies() as calls, patch("src.rag.runner.HybridRagRetriever") as hybrid:
            result = self._run(dry_run=True)
        self.assertEqual(result["binding"]["cell"]["retriever_backend"], "hybrid")
        hybrid.assert_not_called()
        calls["client_factory"].assert_not_called()
        self.runtime["retrieval"] = {"backend": "bm25", "retriever_id": "bm25", "index_dir": str(sparse_dir),
                                     "index_manifest_sha256": sparse_hash, "top_k": 1}
        self._write_config()
        with self._dependencies() as calls:
            result = self._run(dry_run=True)
        self.assertEqual(result["binding"]["cell"]["retriever_backend"], "bm25")
        calls["retriever_factory"].assert_not_called()

    def test_failed_response_defers_scoring_and_resume_only_retries_that_query(self) -> None:
        with self._dependencies() as first:
            client = first["client_factory"].return_value[0]
            original_generate = client.generate_with_metadata

            def fail_first(prompt: str, **kwargs: Any) -> dict[str, Any]:
                result = original_generate(prompt, **kwargs)
                if first["client_calls"] == 1:
                    raise ValueError("synthetic failed response")
                return result

            client.generate_with_metadata = fail_first
            result = self._run()
        self.assertEqual(result["status"], "rag_incomplete")
        self.assertEqual(result["missing_or_failed_queries"], 1)
        self.assertEqual(first["client_calls"], 12000)
        self.assertEqual(first["nli_calls"], 0)
        self.assertFalse((self.work / "run/scores").exists())
        failed = [row for row in read_jsonl(self.work / "run/rag_responses.jsonl") if row.get("error")]
        self.assertEqual(len(failed), 1)
        with self._dependencies() as resumed:
            result = self._run()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(resumed["client_calls"], 1)
        self.assertEqual(result["scored_source_count"], 2000)

    def test_partial_resume_rejects_config_raw_query_and_commit_drift(self) -> None:
        with self._dependencies(interrupt_after=6), self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
            self._run()
        original_config = self.config_path.read_bytes()
        self.runtime["generation"]["max_tokens"] += 1
        self._write_config()
        with self._dependencies() as calls, self.assertRaisesRegex(ValueError, "resume_binding_drift"):
            self._run()
        calls["client_factory"].assert_not_called()
        self.config_path.write_bytes(original_config)
        with self._dependencies() as calls, patch("src.rag.runner.git_snapshot", return_value={"commit": "b" * 40, "dirty": False}):
            with self.assertRaisesRegex(ValueError, "resume_binding_drift"):
                self._run()
        calls["nli_factory"].assert_not_called()
        raw = self.work / "run/rag_responses.jsonl"
        rows = list(read_jsonl(raw))
        rows[0]["query"] = "Tampered question?"
        write_jsonl(rows, raw)
        with self._dependencies() as calls, self.assertRaisesRegex(ValueError, "response_query_mismatch"):
            self._run()
        calls["client_factory"].assert_not_called()
        with self._dependencies(), self.assertRaises(FileExistsError):
            self._run(resume=False)

    def test_legacy_entry_default_and_explicit_v24_boundary(self) -> None:
        spec = importlib.util.spec_from_file_location("v24_formal_cli_boundary", self.root / "scripts/10_run_rag_and_llm_only.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with patch.object(sys, "argv", ["run", "--dataset", "nfcorpus"]):
            args = cli.parse_args()
        self.assertEqual(Path(args.config), self.root / "configs/rag_config.yaml")
        self.assertFalse(args.v24)
        with patch.object(sys, "argv", ["run", "--dataset", "nfcorpus", "--config", str(self.config_path)]):
            with self.assertRaisesRegex(ValueError, "explicit --v24"):
                cli.main()
        for option in ("--force", "--llm-only", "--primary-only"):
            with patch.object(sys, "argv", ["run", "--v24", "--dataset", "nfcorpus", option]):
                with self.assertRaisesRegex(ValueError, "legacy overrides"):
                    cli.main()


if __name__ == "__main__":
    unittest.main()
