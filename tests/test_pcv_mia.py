"""PCV-MIA 行为测试。

中文说明
========
本文件覆盖 PCV-MIA 流水线里几处关键行为的回归测试:

- LLM 配置解析的优先级:CLI 参数 > 环境变量(含 .env)> YAML 默认值,且读取
  .env 时不应污染进程已有的环境变量。
- victim client 构造时,环境变量(base_url/model/api_key_env)能正确覆盖 YAML
  里写死的值;profile 中的 extra_body 也要原样透传给 client。
- embedding 模型构造的"快速失败"约定:hashing 后端被禁用、底层加载失败时必须
  抛错而不是静默回退到别的模型。
- 配对反事实 claim 生成:只替换同类型(同 entity_type)的一个实体,真值 claim
  保持原样,反事实 claim 必须含新实体且不含原实体。
- 立场解析 + PCV 打分:RAG-only PVS 是主分，context gain 仅保留为阴性对照/归因字段。
"""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator
import unittest
from unittest.mock import Mock, patch
import uuid

from src.llm.factory import (
    build_sibling_client,
    build_victim_client,
    llm_profile_identity,
    resolve_effective_llm_profile,
    resolve_llm_profile_name,
)
from src.paired_claims.claim_generator import generate_paired_claims_file
from src.parsing.stance_parser import parse_hybrid_response, parse_stance_files
from src.rag.embeddings import (
    SentenceTransformerEmbeddingModel,
    build_embedding_model,
)
from src.scoring.pcv_scorer import (
    aggregate_hybrid_source,
    build_hybrid_pvs_nli,
    compute_pcv_scores,
    prepare_hybrid_pvs_inputs,
    run_hybrid_pvs_scoring,
    score_hybrid_pair,
    semantic_restoration_score,
)
from src.fact_extraction.fact_extractor import extract_facts_file
from src.utils.env import env_str
from src.utils.hash import sha256_file, sha256_obj
from src.utils.io import load_yaml, read_json, read_jsonl, write_json, write_jsonl


WORKSPACE_TMP = Path(__file__).resolve().parents[1] / ".pytest_tmp"


@contextmanager
def temporary_dir() -> Iterator[Path]:
    """创建一个一次性临时目录(放在工作区 .pytest_tmp 下),供单个用例写入测试文件。"""
    WORKSPACE_TMP.mkdir(exist_ok=True)
    path = WORKSPACE_TMP / f"pcv_{uuid.uuid4().hex}"
    path.mkdir()
    yield path


@contextmanager
def temporary_env(values: dict[str, str], clear: bool = False) -> Iterator[None]:
    """临时替换进程环境变量,退出时无条件还原,避免用例间互相串扰。

    参数:
        values: 要写入的环境变量。
        clear:  为 True 时先清空全部环境变量,用于构造"干净"环境精确验证优先级。
    """
    original = os.environ.copy()
    try:
        if clear:
            os.environ.clear()
        os.environ.update(values)
        yield
    finally:
        # 无论用例是否抛异常,都把环境变量恢复到进入前的快照。
        os.environ.clear()
        os.environ.update(original)


class PcvMiaTests(unittest.TestCase):
    def test_effective_profile_resolves_model_without_constructing_api_client(self) -> None:
        profiles = {
            "active": {"victim": "one"},
            "victim": {
                "profiles": {
                    "one": {
                        "provider": "openai_compatible",
                        "model": "gpt-4.1-mini",
                        "model_env": "PCV_VICTIM_MODEL",
                    }
                }
            },
        }
        with patch("src.llm.factory.env_str", return_value=None):
            resolved = resolve_effective_llm_profile(profiles, "victim")
        self.assertEqual(resolved["model"], "gpt-4.1-mini")

    def test_env_str_reads_dotenv_without_overriding_process_env(self) -> None:
        """验证 env_str 会从 .env 读值,但进程里已存在的同名环境变量优先级更高、不被 .env 覆盖。"""
        with temporary_dir() as tmp:
            dotenv = tmp / ".env"
            dotenv.write_text("PCV_VICTIM_PROFILE=openai_api\n", encoding="utf-8")
            with temporary_env({}, clear=True):
                # 进程环境为空时,只能从 .env 读到值。
                self.assertEqual(env_str("PCV_VICTIM_PROFILE", path=dotenv), "openai_api")
            with temporary_env({"PCV_VICTIM_PROFILE": "alternate_api"}, clear=True):
                # 进程环境已有同名变量时,应以进程值为准,而不是 .env 里的值。
                self.assertEqual(env_str("PCV_VICTIM_PROFILE", path=dotenv), "alternate_api")

    def test_llm_profile_resolution_precedence(self) -> None:
        """验证 profile 解析的优先级:CLI 参数 > 环境变量(.env)> YAML 默认值。"""
        with temporary_dir() as tmp:
            dotenv = tmp / ".env"
            dotenv.write_text("PCV_VICTIM_PROFILE=openai_api\n", encoding="utf-8")
            with temporary_env({}, clear=True):
                # 无 CLI 参数时,环境变量(.env)应压过 YAML 默认值。
                self.assertEqual(
                    resolve_llm_profile_name(
                        "victim",
                        cli_profile=None,
                        config_profile="yaml_default",
                        env_path=dotenv,
                    ),
                    "openai_api",
                )
                # 给了 CLI 参数时,CLI 优先级最高,压过 .env 与 YAML。
                self.assertEqual(
                    resolve_llm_profile_name(
                        "victim",
                        cli_profile="cli_profile",
                        config_profile="yaml_default",
                        env_path=dotenv,
                    ),
                    "cli_profile",
                )
            with temporary_env({}, clear=True):
                # .env 文件不存在时,回退到 YAML 默认值。
                self.assertEqual(
                    resolve_llm_profile_name("victim", config_profile="yaml_default", env_path=tmp / "missing.env"),
                    "yaml_default",
                )

    def test_llm_env_overrides_base_url_model_and_key_env(self) -> None:
        """验证环境变量能覆盖 YAML 里写死的 base_url / model,api_key_env 指向的密钥也被正确读取。"""
        profiles = {
            "active": {"victim": "openai_api"},
            "victim": {
                "profiles": {
                    "openai_api": {
                        "provider": "openai_compatible",
                        "api_key_env": "PCV_VICTIM_API_KEY",
                        "base_url_env": "PCV_VICTIM_BASE_URL",
                        "model_env": "PCV_VICTIM_MODEL",
                        "model_version_env": "PCV_VICTIM_MODEL_VERSION",
                        "base_url": "https://yaml.example/v1",
                        "model": "yaml-model",
                    }
                }
            },
        }
        with temporary_env(
            {
                "PCV_VICTIM_API_KEY": "test-key",
                "PCV_VICTIM_BASE_URL": "https://env.example/v1",
                "PCV_VICTIM_MODEL": "env-model",
                "PCV_VICTIM_MODEL_VERSION": "env-model-2026-07-01",
            },
            clear=True,
        ):
            client, profile = build_victim_client(profiles)
        # profile 解析后的值应来自环境变量,而非 YAML 里写死的 yaml.example / yaml-model。
        self.assertEqual(profile["api_key_env"], "PCV_VICTIM_API_KEY")
        self.assertEqual(profile["base_url"], "https://env.example/v1")
        self.assertEqual(profile["model"], "env-model")
        self.assertEqual(profile["model_version"], "env-model-2026-07-01")
        # 构造出的 client 也应使用环境变量覆盖后的 base_url 与 model。
        self.assertEqual(client.base_url, "https://env.example/v1")
        self.assertEqual(client.model, "env-model")

    def test_llm_profile_extra_body_is_passed_to_client(self) -> None:
        """验证 profile 里的 extra_body(如关闭思考模式)会原样透传到 client。"""
        profiles = {
            "active": {"victim": "dashscope_qwen"},
            "victim": {
                "profiles": {
                    "dashscope_qwen": {
                        "provider": "openai_compatible",
                        "api_key_env": "PCV_VICTIM_API_KEY",
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "model": "qwen3-235b-a22b",
                        "extra_body": {"enable_thinking": False},
                    }
                }
            },
        }
        client, profile = build_victim_client(profiles)
        # extra_body 应在 profile 与 client 两侧都保持原样,确保推理参数能下发给后端。
        self.assertEqual(profile["extra_body"], {"enable_thinking": False})
        self.assertEqual(client.extra_body, {"enable_thinking": False})  # type: ignore[attr-defined]

    def test_ollama_sibling_profile_builds_expected_request_and_identity(self) -> None:
        profiles = load_yaml("configs/llm_profiles.yaml")
        with temporary_env(
            {
                "PCV_SIBLING_API_KEY": "ollama",
                "PCV_SIBLING_BASE_URL": "http://127.0.0.1:11434/v1",
                "PCV_SIBLING_MODEL": "pcv-qwen3-4b:q4km-8k",
                "PCV_SIBLING_MODEL_VERSION": "ollama:0123456789ab",
            },
        ):
            client, profile = build_sibling_client(
                profiles,
                profile_name="ollama_qwen3_4b",
            )

        self.assertEqual(profile["requests_per_minute"], 0)
        self.assertEqual(profile["request_interval_seconds"], 0)
        self.assertFalse(client.stream)  # type: ignore[attr-defined]
        self.assertEqual(client.max_retries, 2)  # type: ignore[attr-defined]
        self.assertEqual(client.retry_backoff_base, 2)  # type: ignore[attr-defined]
        self.assertEqual(client.retry_backoff_max, 30)  # type: ignore[attr-defined]

        captured: dict = {}

        def fake_request(request, _timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            return (
                '{"id":"local-1","model":"pcv-qwen3-4b:q4km-8k",'
                '"choices":[{"finish_reason":"stop",'
                '"message":{"content":"{}"}}]}'
            )

        chat_client = client._client  # type: ignore[attr-defined]
        with temporary_env({"PCV_SIBLING_API_KEY": "ollama"}):
            with patch.object(
                chat_client,
                "_urlopen_with_retries",
                side_effect=fake_request,
            ):
                result = chat_client.chat_with_metadata(
                    "query",
                    temperature=0,
                    max_tokens=1024,
                )

        self.assertEqual(result.provider_model_id, profile["model"])
        self.assertEqual(captured["model"], "pcv-qwen3-4b:q4km-8k")
        self.assertEqual(captured["temperature"], 0)
        self.assertEqual(captured["max_tokens"], 1024)
        self.assertEqual(captured["reasoning_effort"], "none")
        self.assertEqual(captured["seed"], 42)
        self.assertNotIn("stream", captured)

        identity = llm_profile_identity(profile)
        changed = llm_profile_identity({**profile, "model_version": "ollama:drift"})
        self.assertNotEqual(identity["profile_hash"], changed["profile_hash"])
        self.assertNotIn("api_key", identity)

    def test_ollama_sibling_requires_actual_model_id(self) -> None:
        profiles = load_yaml("configs/llm_profiles.yaml")
        with temporary_env(
            {
                "PCV_SIBLING_API_KEY": "ollama",
                "PCV_SIBLING_BASE_URL": "http://127.0.0.1:11434/v1",
                "PCV_SIBLING_MODEL": "pcv-qwen3-4b:q4km-8k",
                "PCV_SIBLING_MODEL_VERSION": "not-a-digest",
            },
        ):
            with self.assertRaisesRegex(ValueError, "actual 12-64 hex model ID"):
                build_sibling_client(
                    profiles,
                    profile_name="ollama_qwen3_4b",
                )

    def test_hashing_embedding_is_disabled(self) -> None:
        """验证 hashing 这种"伪 embedding"已被禁用:无论作为模型名还是 backend 都必须抛 ValueError。"""
        with self.assertRaises(ValueError):
            build_embedding_model("hashing")
        with self.assertRaises(ValueError):
            build_embedding_model("sentence-transformers/all-MiniLM-L6-v2", backend="hashing")

    def test_embedding_load_failure_is_not_silently_fallback(self) -> None:
        """验证 embedding 加载失败时按"快速失败"处理:直接抛原始错误,而不是静默回退到别的实现。"""
        with patch("src.rag.embeddings.SentenceTransformerEmbeddingModel", side_effect=RuntimeError("load failed")):
            # 底层加载抛 RuntimeError,build_embedding_model 应原样把错误抛出来。
            with self.assertRaisesRegex(RuntimeError, "load failed"):
                build_embedding_model("sentence-transformers/missing-model")

    def test_embedding_close_moves_runtime_off_cuda_and_drops_reference(
        self,
    ) -> None:
        class FakeRuntime:
            def __init__(self) -> None:
                self.devices: list[str] = []

            def to(self, device: str) -> None:
                self.devices.append(device)

        embedding = SentenceTransformerEmbeddingModel.__new__(
            SentenceTransformerEmbeddingModel
        )
        runtime = FakeRuntime()
        embedding._model = runtime
        with patch("torch.cuda.is_available", return_value=False):
            embedding.close()
        self.assertEqual(runtime.devices, ["cpu"])
        self.assertIsNone(embedding._model)

    def test_paired_claim_replaces_one_same_type_entity(self) -> None:
        """验证配对反事实生成:只替换同类型(MONEY)的目标实体,真值 claim 不动、反事实 claim 含新值且不含原值。"""
        with temporary_dir() as tmp:
            facts = tmp / "facts.jsonl"
            claims = tmp / "claims.jsonl"
            # 构造一条带 MONEY 实体($48,720)的事实,作为待生成反事实的原料。
            write_jsonl(
                [
                    {
                        "fact_id": "fact_a1_01",
                        "audit_id": "a1",
                        "dataset": "toy",
                        "group": "KB_Member",
                        "factual_claim": "Delta Logistics received $48,720 from Orion Capital on March 12, 2022.",
                        "object_entity": "$48,720",
                        "entity_type": "MONEY",
                    }
                ],
                facts,
            )
            generate_paired_claims_file(facts, claims, perturbation_levels=["light"], force=True)
            row = list(read_jsonl(claims))[0]
            # 真值 claim 应与原事实逐字一致。
            self.assertEqual(row["true_claim"], "Delta Logistics received $48,720 from Orion Capital on March 12, 2022.")
            # 反事实实体必须是被替换后的新值,且确实出现在反事实 claim 中。
            self.assertNotEqual(row["counterfactual_entity"], "$48,720")
            self.assertIn(row["counterfactual_entity"], row["counterfactual_claim"])
            # 原实体不能残留在反事实 claim 里,否则就不是一处干净的替换。
            self.assertNotIn("$48,720", row["counterfactual_claim"])

    def test_stance_and_pcv_score_use_rag_only_pvs(self) -> None:
        """验证 P0 主分使用 RAG-only 成对验证，LLM-only 只进入诊断字段。"""
        with temporary_dir() as tmp:
            queries = tmp / "queries.jsonl"
            rag = tmp / "rag.jsonl"
            llm = tmp / "llm.jsonl"
            parsed = tmp / "parsed.jsonl"
            scores = tmp / "scores.jsonl"
            # 构造一对查询:q_plus 验证真值 claim,q_minus 验证反事实 claim,同属一个 pair。
            write_jsonl(
                [
                    {
                        "query_id": "q_plus",
                        "pair_id": "pair1",
                        "fact_id": "fact1",
                        "audit_id": "a1",
                        "dataset": "toy",
                        "group": "KB_Member",
                        "claim_type": "true",
                        "query_type": "compressed_verification",
                        "expected_entity": "$100",
                        "counterfactual_entity": None,
                        "entity_type": "MONEY",
                    },
                    {
                        "query_id": "q_minus",
                        "pair_id": "pair1",
                        "fact_id": "fact1",
                        "audit_id": "a1",
                        "dataset": "toy",
                        "group": "KB_Member",
                        "claim_type": "counterfactual",
                        "query_type": "compressed_verification",
                        "expected_entity": "$100",
                        "counterfactual_entity": "$120",
                        "entity_type": "MONEY",
                    },
                ],
                queries,
            )
            # RAG 模式下:对真值表态"一致"、对反事实表态"不一致并给出正确值",说明检索上下文起了作用。
            write_jsonl(
                [
                    {
                        "request_id": "rag_plus",
                        "mode": "rag",
                        "query_id": "q_plus",
                        "audit_id": "a1",
                        "dataset": "toy",
                        "group": "KB_Member",
                        "response": "consistent",
                    },
                    {
                        "request_id": "rag_minus",
                        "mode": "rag",
                        "query_id": "q_minus",
                        "audit_id": "a1",
                        "dataset": "toy",
                        "group": "KB_Member",
                        "response": "inconsistent; the corrected value is $100.",
                    },
                ],
                rag,
            )
            # LLM-only 模式下两条都回答"I don't know.",代表不依赖检索时模型自身无法恢复该事实。
            write_jsonl(
                [
                    {
                        "request_id": "llm_plus",
                        "mode": "llm_only",
                        "query_id": "q_plus",
                        "audit_id": "a1",
                        "dataset": "toy",
                        "group": "KB_Member",
                        "response": "I don't know.",
                    },
                    {
                        "request_id": "llm_minus",
                        "mode": "llm_only",
                        "query_id": "q_minus",
                        "audit_id": "a1",
                        "dataset": "toy",
                        "group": "KB_Member",
                        "response": "I don't know.",
                    },
                ],
                llm,
            )
            parse_stance_files("toy", queries, rag, llm, parsed, force=True)
            compute_pcv_scores("toy", parsed, scores, unknown_lambda=0.5, force=True)
            row = list(read_jsonl(scores))[0]
            # RAG 侧:真值表态一致(+1)、反事实表态不一致(+1),合计 cvg_rag = 2.0。
            self.assertEqual(row["cvg_rag"], 2.0)
            # LLM-only 侧:两条都是"不知道",按 unknown_lambda 计入,得到 cvg_llm = -1.0。
            self.assertEqual(row["cvg_llm"], -1.0)
            # context gain = RAG 增益 - LLM-only 增益 = 2.0 - (-1.0) = 3.0。
            self.assertEqual(row["cg_cvg"], 3.0)
            # P0 主分不减 LLM-only，直接取 RAG-only PVS；context gain 只用于归因。
            self.assertEqual(row["pvs_rag"], 2.0)
            self.assertEqual(row["pcv_score"], 2.0)

    def test_weighted_pcv_score_three_views(self) -> None:
        """验证 RAG-only 主分与旧 context-gain 诊断口径同时保留且数值正确。"""
        with temporary_dir() as tmp:
            parsed = tmp / "parsed.jsonl"
            scores = tmp / "scores.jsonl"
            facts = tmp / "facts.jsonl"
            # 两条 fact:高质量(primary,权重0.8) 与 低质量(fallback,权重0.2)。
            write_jsonl(
                [
                    {"fact_id": "f1", "quality_weight": 0.8, "selection_tier": "primary"},
                    {"fact_id": "f2", "quality_weight": 0.2, "selection_tier": "fallback"},
                ],
                facts,
            )
            base = {"audit_id": "a1", "dataset": "toy", "group": "KB_Member", "entity_type": "MONEY"}
            # pair1(f1): cvg_rag=2.0, cvg_llm=-1.0 -> cg_cvg=3.0;pair2(f2): cvg_rag=1.5, cvg_llm=0 -> cg_cvg=1.5。
            write_jsonl(
                [
                    {**base, "pair_id": "p1", "fact_id": "f1", "mode": "rag", "claim_type": "true", "supports_true_claim": True},
                    {**base, "pair_id": "p1", "fact_id": "f1", "mode": "rag", "claim_type": "counterfactual", "corrects_to_original_entity": True},
                    {**base, "pair_id": "p1", "fact_id": "f1", "mode": "llm_only", "claim_type": "true", "says_unknown": True},
                    {**base, "pair_id": "p1", "fact_id": "f1", "mode": "llm_only", "claim_type": "counterfactual", "says_unknown": True},
                    {**base, "pair_id": "p2", "fact_id": "f2", "mode": "rag", "claim_type": "true", "supports_true_claim": True},
                    {**base, "pair_id": "p2", "fact_id": "f2", "mode": "rag", "claim_type": "counterfactual", "rejects_counterfactual": True},
                    {**base, "pair_id": "p2", "fact_id": "f2", "mode": "llm_only", "claim_type": "true"},
                    {**base, "pair_id": "p2", "fact_id": "f2", "mode": "llm_only", "claim_type": "counterfactual"},
                ],
                parsed,
            )
            compute_pcv_scores("toy", parsed, scores, unknown_lambda=0.5, facts_path=facts, thresholds=[2.5], force=True)
            row = list(read_jsonl(scores))[0]
            # 不加权简单平均: (3.0 + 1.5) / 2 = 2.25
            self.assertEqual(row["cg_cvg"], 2.25)
            # RAG-only 主分简单平均: (2.0 + 1.5) / 2 = 1.75。
            self.assertAlmostEqual(row["pcv_score"], 1.75)
            # 旧质量加权 context gain 仅作为诊断字段保留。
            self.assertAlmostEqual(row["pcv_score_context_gain_weighted"], 2.7)
            # 仅 primary 口径: 只用 f1(primary) -> 3.0
            self.assertEqual(row["pcv_score_primary"], 3.0)
            self.assertEqual(row["num_primary_pairs"], 1)
            # 阈值判定跟随 RAG-only 主分，而不是旧 context-gain 口径。
            self.assertFalse(row["predicted_member_t2.5"])

    def test_source_level_score_aggregates_multiple_chunks(self) -> None:
        """同一 source 的多个 audit/chunk 必须聚合为一行并取等权均值。"""
        with temporary_dir() as tmp:
            parsed = tmp / "parsed.jsonl"
            scores = tmp / "toy_pcv_scores.jsonl"
            rows = []
            for audit_id, support in (("a1", True), ("a2", False)):
                base = {
                    "audit_id": audit_id,
                    "source_id": "source-1",
                    "source_key": "toy::source-1",
                    "dataset": "toy",
                    "group": "KB_Member",
                    "pair_id": f"p-{audit_id}",
                    "fact_id": f"f-{audit_id}",
                    "entity_type": "MONEY",
                }
                rows.extend(
                    [
                        {**base, "mode": "rag", "claim_type": "true", "supports_true_claim": support},
                        {**base, "mode": "rag", "claim_type": "counterfactual", "corrects_to_original_entity": support},
                        {**base, "mode": "llm_only", "claim_type": "true"},
                        {**base, "mode": "llm_only", "claim_type": "counterfactual"},
                    ]
                )
            write_jsonl(rows, parsed)
            compute_pcv_scores("toy", parsed, scores, force=True)
            source_rows = list(read_jsonl(tmp / "toy_pcv_scores_source_scores.jsonl"))
            self.assertEqual(len(source_rows), 1)
            self.assertEqual(source_rows[0]["num_chunks"], 2)
            self.assertEqual(source_rows[0]["pcv_score"], 1.0)

    def test_fact_extraction_guarantees_coverage(self) -> None:
        """方案 D:每篇有可成句实体的文档都保底产出事实,且每条带 quality_weight/selection_tier。"""
        with temporary_dir() as tmp:
            bench = tmp / "bench.jsonl"
            facts = tmp / "facts.jsonl"
            write_jsonl(
                [
                    {
                        "audit_id": "a1", "dataset": "toy", "group": "KB_Member", "doc_id": "d1",
                        "text": "Delta Logistics received $48,720 from Orion Capital on March 12, 2022 under the service agreement.",
                    },
                ],
                bench,
            )
            manifest = extract_facts_file(bench, facts, guarantee_min_facts=1, force=True)
            rows = list(read_jsonl(facts))
            # 该文档必须保底产出至少一条事实。
            self.assertGreaterEqual(len(rows), 1)
            for r in rows:
                self.assertIn("quality_weight", r)
                self.assertIn(r["selection_tier"], {"primary", "fallback"})
                self.assertGreaterEqual(float(r["quality_weight"]), 0.0)
            # manifest 记录覆盖率与分层统计。
            self.assertIn("coverage_by_group", manifest)
            self.assertIn("facts_by_tier", manifest)
            self.assertEqual(manifest["coverage_by_group"]["KB_Member"], 1.0)


class HybridPvsTests(unittest.TestCase):
    """V24 混合评分的离线契约测试；语义概率由 mock 提供，不声称验证模型质量。"""

    @staticmethod
    def _nli(forward: float = 0.9, reverse: float = 0.8) -> Mock:
        predictor = Mock(spec=["probabilities"])
        predictor.probabilities.return_value = [
            {"entailment": value, "neutral": 1.0 - value, "contradiction": 0.0}
            for value in (forward, reverse)
        ]
        return predictor

    @staticmethod
    def _response(stance: str, correction: str | None = None) -> str:
        return json.dumps({"stance": stance, "correction_entity": correction})

    def _pair(self, **overrides: Any) -> dict[str, Any]:
        arguments = {
            "dataset": "toy", "source_key": "toy::s1", "pair_id": "p0",
            "original_entity": "43 RA patients", "plus_response": "Consistent",
            "minus_response": "Inconsistent: 43 RA patients",
        }
        return score_hybrid_pair(**{**arguments, **overrides})

    def test_explicit_response_formats_preserve_raw_text(self) -> None:
        cases = [
            ("Yes.", "supported", None),
            ("Consistent", "supported", None),
            ("No!", "contradicted", None),
            ("Inconsistent: NHL", "contradicted", "NHL"),
            ("  Inconsistent: forty-three RA patients  ", "contradicted", "forty-three RA patients"),
            ("I don't know", "insufficient", None),
            ("I don’t know.", "insufficient", None),
            (self._response("supported"), "supported", None),
            (self._response("contradicted", "NHL"), "contradicted", "NHL"),
            (self._response("insufficient"), "insufficient", None),
        ]
        for raw, stance, correction in cases:
            with self.subTest(raw=raw):
                parsed = parse_hybrid_response(raw)
                self.assertEqual(parsed["parse_status"], "parsed")
                self.assertEqual(parsed["raw_response"], raw)
                self.assertEqual((parsed["stance"], parsed["correction_entity"]), (stance, correction))
        self.assertEqual(parse_hybrid_response(b"No.")["stance"], "contradicted")

    def test_no_without_correction_is_valid_and_does_not_change_v23_parser(self) -> None:
        from src.evaluation.restoration_first_v23 import parse_response

        raw = self._response("contradicted")
        self.assertEqual(parse_response(raw)["parse_status"], "invalid")
        for response in (raw, self._response("contradicted", "  "), "No.", "Inconsistent:"):
            with self.subTest(response=response):
                nli = self._nli()
                score = self._pair(minus_response=response, nli=nli)
                self.assertEqual(score["score_status"], "scored")
                self.assertEqual(score["minus_response"]["stance"], "contradicted")
                self.assertEqual(score["counter_acceptance"], 0.0)
                self.assertEqual(score["restoration"], 0.0)
                self.assertEqual(score["pair_pvs"], 0.0)
                nli.probabilities.assert_not_called()

    def test_malformed_or_free_text_does_not_infer_support_from_entity_mentions(self) -> None:
        cases = [
            'The trial did not include 43 RA patients.',
            'No, it did not include 43 RA patients.',
            self._response("supported", "43 RA patients"),
            self._response("insufficient", "43 RA patients"),
            '{"stance":"supported","stance":"contradicted","correction_entity":null}',
            '{"stance":"contradicted","correction_entity":43}',
            '{"stance":"supported","correction_entity":null,"confidence":0.9}',
            '{"stance":"unknown","correction_entity":null}',
            '{"stance":"contradicted","correction_entity":NaN}',
            b'\xff',
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertEqual(parse_hybrid_response(raw)["parse_status"], "invalid")
                score = self._pair(plus_response=raw)
                self.assertEqual(score["score_status"], "response_error")
                self.assertIsNone(score["pair_pvs"])

    def test_positive_support_uses_stance_endpoints(self) -> None:
        for raw, expected in [("Yes.", 1.0), ("No.", 0.0), ("I don't know", 0.0)]:
            with self.subTest(raw=raw):
                score = self._pair(plus_response=raw)
                self.assertEqual(score["positive_support"], expected)
                self.assertEqual(score["restoration"], 1.0)
                self.assertEqual(score["pair_pvs"], expected)

    def test_accepting_counter_is_one_and_negative_margin_is_clipped(self) -> None:
        score = self._pair(minus_response=self._response("supported"))
        self.assertEqual(score["counter_acceptance"], 1.0)
        self.assertEqual(score["restoration"], 0.0)
        self.assertEqual(score["restoration_margin"], 0.0)
        self.assertEqual(score["non_acceptance"], 0.0)
        self.assertEqual(score["pair_pvs"], 0.0)

    def test_unknown_is_valid_zero_support_and_not_a_runtime_failure(self) -> None:
        score = self._pair(plus_response="I don't know", minus_response="I don't know")
        self.assertEqual(score["score_status"], "scored")
        for key in ("positive_support", "counter_acceptance", "restoration", "pair_pvs"):
            self.assertEqual(score[key], 0.0)
        self.assertEqual(score["non_acceptance"], 1.0)

    def test_exact_normalized_restoration_skips_nli(self) -> None:
        nli = self._nli()
        score = self._pair(minus_response=self._response("contradicted", "４３　ra\tpatients"), nli=nli)
        self.assertEqual(score["restoration"], 1.0)
        self.assertEqual(score["pair_pvs"], 1.0)
        nli.probabilities.assert_not_called()

    def test_fixed_ra_exact_restoration_is_one_without_nli(self) -> None:
        original = "43 RA patients"
        nli = self._nli()
        score = self._pair(
            original_entity=original,
            minus_response=self._response("contradicted", original),
            nli=nli,
        )
        self.assertEqual(score["score_status"], "scored")
        self.assertEqual(score["restoration"], 1.0)
        self.assertEqual(score["pair_pvs"], 1.0)
        nli.probabilities.assert_not_called()

    def test_fixed_ra_non_exact_cases_use_bidirectional_nli_without_shortcut(self) -> None:
        original = "43 RA patients"
        corrections = [
            "forty-three participants with rheumatoid arthritis",
            "43 patients",
            "44 RA patients",
            "43 patients without rheumatoid arthritis",
        ]
        # 所有非 exact case 使用相同的人工概率，只验证接口和公式，不预设真实语义排序。
        for correction in corrections:
            for forward, reverse in ((0.9, 0.4), (0.4, 0.9)):
                with self.subTest(correction=correction, forward=forward, reverse=reverse):
                    nli = self._nli(forward, reverse)
                    score = self._pair(
                        original_entity=original,
                        minus_response=self._response("contradicted", correction),
                        nli=nli,
                    )
                    corrected = f"The corrected value is {correction}."
                    true = f"The corrected value is {original}."
                    nli.probabilities.assert_called_once_with([(corrected, true), (true, corrected)])
                    self.assertEqual(score["score_status"], "scored")
                    self.assertEqual(score["positive_support"], 1.0)
                    self.assertEqual(score["counter_acceptance"], 0.0)
                    self.assertEqual(score["restoration"], min(forward, reverse))
                    self.assertEqual(score["restoration_margin"], min(forward, reverse))
                    self.assertEqual(score["pair_pvs"], min(forward, reverse))

    def test_semantic_paraphrase_and_abbreviation_use_only_value_pairs(self) -> None:
        cases = [
            ("43 RA patients", "forty-three participants with rheumatoid arthritis"),
            ("non-Hodgkin lymphoma", "NHL"),
        ]
        for original, correction in cases:
            with self.subTest(original=original):
                nli = self._nli(0.94, 0.81)
                score = self._pair(original_entity=original,
                                   minus_response=self._response("contradicted", correction), nli=nli)
                self.assertAlmostEqual(score["restoration"], 0.81)
                self.assertAlmostEqual(score["pair_pvs"], 0.81)
                corrected = f"The corrected value is {correction}."
                true = f"The corrected value is {original}."
                nli.probabilities.assert_called_once_with([(corrected, true), (true, corrected)])

    def test_one_way_entailment_is_not_treated_as_full_equivalence(self) -> None:
        nli = self._nli(0.97, 0.12)
        value = semantic_restoration_score("patients", "43 RA patients", nli=nli)
        self.assertEqual(value, 0.12)

    def test_different_numbers_diseases_and_substrings_do_not_take_exact_shortcut(self) -> None:
        for original, correction in [("43", "44"), ("43", "143"), ("4.3", "43"),
                                     ("rheumatoid arthritis", "osteoarthritis")]:
            with self.subTest(original=original, correction=correction):
                nli = self._nli(0.04, 0.02)
                self.assertEqual(semantic_restoration_score(correction, original, nli=nli), 0.02)
                nli.probabilities.assert_called_once()

    def test_missing_and_failed_responses_are_unscored(self) -> None:
        for changes, side, status in [
            ({"plus_response": None}, "plus_response", "missing"),
            ({"minus_response": "  "}, "minus_response", "missing"),
            ({"plus_error": True}, "plus_response", "generator_error"),
            ({"minus_error": True}, "minus_response", "generator_error"),
        ]:
            with self.subTest(changes=changes):
                score = self._pair(**changes)
                self.assertEqual(score["score_status"], "response_error")
                self.assertEqual(score[side]["parse_status"], status)
                self.assertIsNone(score["pair_pvs"])

    def test_missing_nli_or_runtime_failure_is_not_a_zero_restoration(self) -> None:
        nli = self._nli()
        nli.probabilities.side_effect = RuntimeError("hidden diagnostic payload")
        for predictor in (None, nli):
            with self.subTest(predictor=predictor):
                score = self._pair(minus_response="Inconsistent: NHL", nli=predictor)
                self.assertEqual(score["score_status"], "nli_error")
                self.assertEqual(score["positive_support"], 1.0)
                self.assertIsNone(score["restoration"])
                self.assertIsNone(score["pair_pvs"])
                self.assertNotIn("hidden diagnostic payload", json.dumps(score))

    def test_invalid_nli_outputs_are_unscored(self) -> None:
        valid = {"entailment": 0.8, "neutral": 0.1, "contradiction": 0.1}
        invalid = [
            [], [valid], [{"entailment": 0.8}, valid],
            [{**valid, "entailment": float("nan")}, valid],
            [{**valid, "entailment": float("inf")}, valid],
            [{**valid, "entailment": 1.1}, valid],
            [{**valid, "neutral": -0.1}, valid],
            [{**valid, "entailment": True}, valid],
            [{**valid, "entailment": 0.2}, valid],
        ]
        for rows in invalid:
            with self.subTest(rows=rows):
                nli = self._nli()
                nli.probabilities.return_value = rows
                score = self._pair(minus_response="Inconsistent: forty-three RA patients", nli=nli)
                self.assertEqual(score["score_status"], "nli_error")
                self.assertIsNone(score["pair_pvs"])

    def test_three_pairs_keep_mean_primary_and_median_diagnostic(self) -> None:
        pairs = [self._pair(pair_id="p0"),
                 self._pair(pair_id="p1", minus_response="Inconsistent: forty-three RA patients", nli=self._nli()),
                 self._pair(pair_id="p2", minus_response="Consistent")]
        source = aggregate_hybrid_source(pairs, dataset="toy", source_key="toy::s1")
        self.assertEqual(source["score_status"], "scored")
        self.assertAlmostEqual(source["source_pvs_mean"], 0.6)
        self.assertEqual(source["source_pvs"], source["source_pvs_mean"])
        self.assertEqual(source["source_pvs_median"], 0.8)
        self.assertEqual([row["pair_id"] for row in source["pair_scores"]], ["p0", "p1", "p2"])

    def test_insufficient_or_incomplete_source_does_not_average_remaining_pairs(self) -> None:
        good = [self._pair(pair_id="p0"), self._pair(pair_id="p1")]
        for pairs, status in [([], "insufficient_pairs"), (good, "insufficient_pairs"),
                              (good + [self._pair(pair_id="p2", minus_response=None)], "incomplete")]:
            with self.subTest(status=status, count=len(pairs)):
                source = aggregate_hybrid_source(pairs, dataset="toy", source_key="toy::s1")
                self.assertEqual(source["score_status"], status)
                for field in ("source_pvs", "source_pvs_mean", "source_pvs_median"):
                    self.assertIsNone(source[field])

    def test_source_rejects_identity_duplicates_budget_and_invalid_scores(self) -> None:
        good = [self._pair(pair_id=f"p{i}") for i in range(3)]
        variants = [good + [self._pair(pair_id="p3")], [good[0], good[0], good[2]]]
        for field, value in [("source_key", "toy::s2"), ("dataset", "other"),
                             ("scoring_kind", "legacy"), ("pair_pvs", float("nan")),
                             ("pair_pvs", 1.1), ("pair_pvs", True)]:
            variants.append([good[0], good[1], {**good[2], field: value}])
        for pairs in variants:
            with self.subTest(pairs=pairs):
                with self.assertRaises(ValueError):
                    aggregate_hybrid_source(pairs, dataset="toy", source_key="toy::s1")
        with self.assertRaises(ValueError):
            self._pair(pair_id="")
        with self.assertRaises(ValueError):
            self._pair(original_entity="  ")

    def test_config_builds_existing_fixed_nli_with_no_real_model_load(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = load_yaml(root / "configs" / "restoration_first_v24.yaml")
        with patch("src.scoring.pcv_scorer.TransformersNLIPredictor") as factory:
            predictor = build_hybrid_pvs_nli(config, root)
        self.assertIs(predictor, factory.return_value)
        settings = config["scoring"]["restoration"]["nli"]
        factory.assert_called_once_with(
            snapshot_dir=(root / settings["snapshot_dir"]).resolve(),
            model_id=settings["model_id"], revision=settings["revision"], device="cuda",
            require_cuda=True, batch_size=settings["batch_size"], max_length=settings["max_length"],
        )

    def test_config_rejects_mapping_formula_aggregation_or_model_drift(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = load_yaml(root / "configs" / "restoration_first_v24.yaml")
        changes = [
            (("support_mapping", "insufficient"), 0.5),
            (("pair_formula",), "S+ + R-"), (("source_aggregation",), "median"),
            (("pairs_per_source",), 4),
            (("restoration", "value_template"), "Question: {value}"),
            (("restoration", "nli", "model_id"), "other-model"),
            (("restoration", "nli", "revision"), "other-revision"),
            (("restoration", "nli", "device"), "cpu"),
            (("restoration", "nli", "local_files_only"), False),
        ]
        for path, value in changes:
            with self.subTest(path=path):
                altered = deepcopy(config)
                parent = altered["scoring"]
                for key in path[:-1]:
                    parent = parent[key]
                parent[path[-1]] = value
                with patch("src.scoring.pcv_scorer.TransformersNLIPredictor") as factory:
                    with self.assertRaises(ValueError):
                        build_hybrid_pvs_nli(altered, root)
                    factory.assert_not_called()


class HybridPvsEntryTests(unittest.TestCase):
    """现有构造产物到离线评分入口的集成测试；不调用模型或外部服务。"""

    root = Path(__file__).resolve().parents[1]

    @classmethod
    def _cli(cls) -> Any:
        spec = importlib.util.spec_from_file_location("hybrid_scoring_cli_test", cls.root / "scripts/11_parse_stance_and_score.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        pairs, responses = [], []
        original = "43 RA patients"
        for index, counter in enumerate(("44 RA patients", "45 RA patients", "46 RA patients")):
            pair = {
                "dataset": "nfcorpus", "source_key": "nfcorpus::synthetic", "chunk_sha256": "a" * 64,
                "pair_id": f"p{index}", "original_entity": original, "counter_entity": counter,
                "q_plus_text": f"Did the Atlas trial enroll {original}?",
                "q_minus_text": f"Did the Atlas trial enroll {counter}?",
            }
            pairs.append(pair)
            for polarity, claim_type, text, response in (
                ("Q_plus", "true", pair["q_plus_text"], "Yes."),
                ("Q_minus", "counterfactual", pair["q_minus_text"], f"Inconsistent: {original}"),
            ):
                responses.append({
                    "dataset": pair["dataset"], "source_key": pair["source_key"], "pair_id": pair["pair_id"],
                    "query_id": sha256_obj({"pair_id": pair["pair_id"], "polarity": polarity}),
                    "claim_type": claim_type, "query": text, "response": response, "error": None,
                    "mode": "rag", "concrete_model": "synthetic-victim", "provider_model_id": "synthetic-victim",
                    "generator_family": "gpt", "generator_version": "synthetic-revision",
                    "retriever_backend": "dense", "retriever_id": "synthetic-index",
                    "variant_id": "original", "context_control": "retrieved", "system_fingerprint": "synthetic-fp",
                })
        return pairs, responses

    def _arguments(self, tmp: Path, pairs: list, responses: list) -> dict[str, Any]:
        write_jsonl(pairs, tmp / "pairs.jsonl")
        write_jsonl(responses, tmp / "responses.jsonl")
        return {
            "dataset": "nfcorpus", "project_root": self.root,
            "config_path": "configs/restoration_first_v24.yaml", "pairs_path": tmp / "pairs.jsonl",
            "responses_path": tmp / "responses.jsonl", "output_dir": tmp / "scores",
        }

    def test_cli_scores_same_slot_pairs_and_preserves_query_text_and_order(self) -> None:
        pairs, responses = self._rows()
        responses[3]["response"] = "Inconsistent: forty-three participants with rheumatoid arthritis"
        responses[5]["response"] = "Yes."
        nli = HybridPvsTests._nli()
        cli = self._cli()
        with temporary_dir() as tmp:
            arguments = self._arguments(tmp, pairs, list(reversed(responses)))
            before = sha256_file(tmp / "pairs.jsonl")
            argv = ["score", "--dataset", "nfcorpus", "--v24-hybrid", "--pairs", str(arguments["pairs_path"]),
                    "--responses", str(arguments["responses_path"]), "--output-dir", str(arguments["output_dir"])]
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()), \
                    patch("src.scoring.pcv_scorer.build_hybrid_pvs_nli", return_value=nli) as factory, \
                    patch.object(cli, "resolve_generator_from_pipeline_config", side_effect=AssertionError("legacy called")):
                self.assertEqual(cli.main(), 0)
            factory.assert_called_once()
            nli.probabilities.assert_called_once()
            scored = list(read_jsonl(tmp / "scores/pair_scores.jsonl"))
            source = list(read_jsonl(tmp / "scores/source_scores.jsonl"))[0]
            summary = read_json(tmp / "scores/scoring_summary.json")
            self.assertEqual([row["pair_id"] for row in scored], ["p0", "p1", "p2"])
            self.assertEqual([row["pair_pvs"] for row in scored], [1.0, 0.8, 0.0])
            self.assertAlmostEqual(source["source_pvs_mean"], 0.6)
            self.assertEqual(source["source_pvs"], source["source_pvs_mean"])
            self.assertEqual(source["source_pvs_median"], 0.8)
            self.assertEqual(source["concrete_model"], "synthetic-victim")
            self.assertEqual(source["retriever_id"], "synthetic-index")
            self.assertEqual(summary["query_count"], 6)
            self.assertEqual(summary["pair_scores_sha256"], sha256_file(tmp / "scores/pair_scores.jsonl"))
            self.assertEqual(summary["pairs_sha256"], before)
            self.assertEqual(sha256_file(tmp / "pairs.jsonl"), before)
            for pair, score in zip(pairs, scored):
                self.assertEqual(score["q_plus_text"], pair["q_plus_text"])
                self.assertEqual(score["q_minus_text"], pair["q_minus_text"])

    def test_smoke_preflight_does_not_score_load_model_or_write_outputs(self) -> None:
        pairs, _ = self._rows()
        identity = {key: pairs[0][key] for key in ("dataset", "source_key", "chunk_sha256")}
        smoke = [{"source": identity, "construction": {**identity, "selected_pairs": pairs, "selected_pair_count": 3}}]
        with temporary_dir() as tmp:
            arguments = self._arguments(tmp, smoke, [])
            arguments.pop("responses_path")
            with patch("src.scoring.pcv_scorer.build_hybrid_pvs_nli", side_effect=AssertionError("model loaded")), \
                    patch("src.scoring.pcv_scorer.score_hybrid_pair", side_effect=AssertionError("scoring called")):
                summary = run_hybrid_pvs_scoring(**arguments, dry_run=True)
            self.assertEqual(summary["status"], "prepared_inputs_only")
            self.assertEqual((summary["source_count"], summary["pair_count"], summary["query_count"]), (1, 3, 6))
            self.assertEqual(summary["missing_response_count"], 6)
            self.assertFalse(summary["nli_loaded"])
            self.assertFalse(summary["formal_freeze_performed"])
            self.assertFalse((tmp / "scores").exists())

    def test_missing_failed_or_malformed_response_leaves_source_unscored(self) -> None:
        pairs, responses = self._rows()
        variants = [responses[1:], [{**responses[0], "error": "synthetic failure"}, *responses[1:]],
                    [{**responses[0], "response": "unstructured answer"}, *responses[1:]]]
        for rows in variants:
            with self.subTest(first=rows[0]["response"]), temporary_dir() as tmp:
                arguments = self._arguments(tmp, pairs, rows)
                with patch("src.scoring.pcv_scorer.build_hybrid_pvs_nli", side_effect=AssertionError("model loaded")):
                    summary = run_hybrid_pvs_scoring(**arguments)
                source = list(read_jsonl(tmp / "scores/source_scores.jsonl"))[0]
                self.assertEqual(summary["status"], "incomplete")
                self.assertEqual(source["score_status"], "incomplete")
                self.assertIsNone(source["source_pvs_mean"])
                self.assertIsNone(source["source_pvs_median"])
                self.assertIsNone(source["pair_scores"][0]["pair_pvs"])

    def test_non_exact_without_local_nli_fails_before_writing_scores(self) -> None:
        pairs, responses = self._rows()
        responses[1]["response"] = "Inconsistent: forty-three participants with rheumatoid arthritis"
        with temporary_dir() as tmp:
            arguments = self._arguments(tmp, pairs, responses)
            with patch("src.scoring.pcv_scorer.build_hybrid_pvs_nli", side_effect=FileNotFoundError("missing local weights")):
                with self.assertRaises(FileNotFoundError):
                    run_hybrid_pvs_scoring(**arguments)
            self.assertFalse((tmp / "scores").exists())

    def test_duplicate_cross_source_and_drifted_queries_are_rejected(self) -> None:
        pairs, responses = self._rows()
        variants = [responses + [responses[0]]]
        for field, value in (("dataset", "scidocs"), ("source_key", "nfcorpus::other"),
                             ("pair_id", "other"), ("claim_type", "counterfactual"),
                             ("query_id", "other"), ("query", "Changed question?"),
                             ("chunk_sha256", "b" * 64)):
            variants.append([{**responses[0], field: value}, *responses[1:]])
        for rows in variants:
            with self.subTest(first=rows[0]):
                with self.assertRaisesRegex(ValueError, "hybrid_pvs_"):
                    prepare_hybrid_pvs_inputs(pairs, rows, dataset="nfcorpus")

    def test_mixed_runtime_cells_or_provider_drift_are_rejected(self) -> None:
        pairs, responses = self._rows()
        for field in ("mode", "concrete_model", "provider_model_id", "retriever_backend", "retriever_id",
                      "variant_id", "context_control", "generator_version", "system_fingerprint"):
            with self.subTest(field=field):
                rows = [*responses[:-1], {**responses[-1], field: "other"}]
                with self.assertRaisesRegex(ValueError, "hybrid_pvs_"):
                    prepare_hybrid_pvs_inputs(pairs, rows, dataset="nfcorpus")

    def test_selected_duplicates_chunk_drift_and_excess_pairs_are_rejected(self) -> None:
        pairs, _ = self._rows()
        identity = {key: pairs[0][key] for key in ("dataset", "source_key", "chunk_sha256")}
        empty_source = {**identity, "selected_pairs": []}
        variants = [pairs + [pairs[0]], pairs + [{**pairs[0], "pair_id": "p3"}],
                    [pairs[0], {**pairs[1], "chunk_sha256": "b" * 64}, pairs[2]],
                    [{**pairs[0], "chunk_sha256": "invalid"}], [empty_source, empty_source],
                    [empty_source, {**empty_source, "source_key": "nfcorpus::duplicate-chunk"}]]
        for rows in variants:
            with self.subTest(count=len(rows)):
                with self.assertRaisesRegex(ValueError, "hybrid_pvs_"):
                    prepare_hybrid_pvs_inputs(rows, [], dataset="nfcorpus")

    def test_zero_and_two_pair_sources_are_preserved_as_insufficient(self) -> None:
        pairs, _ = self._rows()
        identity = {key: pairs[0][key] for key in ("dataset", "source_key", "chunk_sha256")}
        rows = [{**identity, "selected_pairs": pairs[:2]},
                {**identity, "source_key": "nfcorpus::empty", "chunk_sha256": "b" * 64, "selected_pairs": []}]
        with temporary_dir() as tmp:
            arguments = self._arguments(tmp, rows, [])
            summary = run_hybrid_pvs_scoring(**arguments)
            sources = list(read_jsonl(tmp / "scores/source_scores.jsonl"))
            self.assertEqual(summary["source_count"], 2)
            self.assertEqual(summary["pair_count"], 2)
            self.assertEqual([row["score_status"] for row in sources], ["insufficient_pairs", "insufficient_pairs"])
            self.assertTrue(all(row["source_pvs"] is None for row in sources))

    def test_existing_output_is_never_overwritten(self) -> None:
        pairs, responses = self._rows()
        with temporary_dir() as tmp:
            arguments = self._arguments(tmp, pairs, responses)
            output = arguments["output_dir"]
            output.mkdir()
            (output / "sentinel.txt").write_text("existing result", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                run_hybrid_pvs_scoring(**arguments)
            self.assertEqual((output / "sentinel.txt").read_text(encoding="utf-8"), "existing result")

    def test_scoring_config_drift_fails_during_preflight(self) -> None:
        pairs, responses = self._rows()
        with temporary_dir() as tmp:
            arguments = self._arguments(tmp, pairs, responses)
            config = load_yaml(self.root / arguments["config_path"])
            config["scoring"]["source_aggregation"] = "median"
            write_json(config, tmp / "changed.yaml")
            arguments["config_path"] = tmp / "changed.yaml"
            with self.assertRaisesRegex(ValueError, "hybrid_pvs_config_mismatch"):
                run_hybrid_pvs_scoring(**arguments, dry_run=True)
            self.assertFalse((tmp / "scores").exists())

    def test_legacy_defaults_remain_and_v24_never_silently_uses_legacy(self) -> None:
        cli = self._cli()
        with patch.object(sys, "argv", ["score", "--dataset", "nfcorpus"]):
            args = cli.parse_args()
        self.assertEqual(Path(args.config), self.root / "configs/pcv_attack_config.yaml")
        self.assertFalse(args.v24_hybrid)
        with patch.object(sys, "argv", ["score", "--dataset", "nfcorpus", "--config",
                                        str(self.root / "configs/restoration_first_v24.yaml")]):
            with self.assertRaisesRegex(ValueError, "explicit --v24-hybrid"):
                cli.main()
        for extras in (["--dry-run"], ["--v24-hybrid"], ["--v24-hybrid", "--pairs", "x", "--dry-run", "--force"],
                       ["--v24-hybrid", "--pairs", "x", "--dry-run", "--rag-config", "other.yaml"]):
            with patch.object(sys, "argv", ["score", "--dataset", "nfcorpus", *extras]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    cli.parse_args()
                self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
