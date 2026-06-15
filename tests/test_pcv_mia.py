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
- 立场解析 + PCV/CG-CMS 打分:context gain(RAG 相对 LLM-only 的增益)的计算,
  即最终得分会扣除 LLM-only 自身就能恢复的部分。
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from typing import Iterator
import unittest
from unittest.mock import patch
import uuid

from src.llm.factory import build_victim_client, resolve_llm_profile_name
from src.paired_claims.claim_generator import generate_paired_claims_file
from src.parsing.stance_parser import parse_stance_files
from src.rag.embeddings import build_embedding_model
from src.scoring.pcv_scorer import compute_pcv_scores
from src.fact_extraction.fact_extractor import extract_facts_file
from src.utils.env import env_str
from src.utils.io import read_jsonl, write_jsonl, write_json


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
            },
            clear=True,
        ):
            client, profile = build_victim_client(profiles)
        # profile 解析后的值应来自环境变量,而非 YAML 里写死的 yaml.example / yaml-model。
        self.assertEqual(profile["api_key_env"], "PCV_VICTIM_API_KEY")
        self.assertEqual(profile["base_url"], "https://env.example/v1")
        self.assertEqual(profile["model"], "env-model")
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

    def test_stance_and_pcv_score_use_context_gain(self) -> None:
        """验证立场解析 + PCV 打分使用 context gain:最终 pcv_score 为 RAG 增益扣除 LLM-only 自身增益。"""
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
            # 最终 pcv_score 取 context gain,体现"扣除 LLM-only 自身恢复"后的成员信号。
            # 未提供 facts_path 时权重退化为 1.0(向后兼容):加权平均 == 简单平均 == cg_cvg。
            self.assertEqual(row["pcv_score"], 3.0)

    def test_weighted_pcv_score_three_views(self) -> None:
        """方案 D:质量加权聚合给出三口径(cg_cvg/pcv_score/pcv_score_primary)且数值正确。"""
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
            compute_pcv_scores("toy", parsed, scores, unknown_lambda=0.5, facts_path=facts, force=True)
            row = list(read_jsonl(scores))[0]
            # 不加权简单平均: (3.0 + 1.5) / 2 = 2.25
            self.assertEqual(row["cg_cvg"], 2.25)
            # 质量加权: (0.8*3.0 + 0.2*1.5) / (0.8+0.2) = 2.7
            self.assertAlmostEqual(row["pcv_score"], 2.7)
            # 仅 primary 口径: 只用 f1(primary) -> 3.0
            self.assertEqual(row["pcv_score_primary"], 3.0)
            self.assertEqual(row["num_primary_pairs"], 1)

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


if __name__ == "__main__":
    unittest.main()
