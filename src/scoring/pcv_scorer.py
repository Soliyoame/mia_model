"""PCV-MIA scoring.

This module computes the Paired Verification Score (PVS) used by PCV-MIA.

CVG = SupportScore(Q+) + CorrectionScore(Q-) - FalseAcceptancePenalty(Q-)
The operational black-box attack uses CVG_RAG directly. CVG_LLM and
CG-CVG = CVG_RAG - CVG_LLM are retained as experimental controls.

中文说明
========
本文件对应流水线第 11 步的"打分"部分，是把"模型的态度"换算成"成员可能性分数"的
核心算法。理解三个公式就理解了整个攻击的判定逻辑：

- 对每个事实，我们准备一对问题：Q+(真实声明) 和 Q-(反事实/伪造声明)。
- CVG(反事实验证差距) = 支持分(对Q+) + 纠正分(对Q-) - 误受惩罚(对Q-)。
  直觉：一个"真懂这份文档"的系统，应该【支持真实声明】并且【纠正伪造声明】；
  如果它把伪造声明也当真接受了，就要扣分。
- 同一套打分分别在两种模式下算一遍：CVG_RAG(带检索) 和 CVG_LLM(纯模型)。
- CG-CVG = CVG_RAG - CVG_LLM，即"检索到底带来了多少额外能力"。这个差值越大，
  说明该文档越可能真的躺在 RAG 知识库里(成员)。

输入：第 11 步前半段解析出的"态度(stance)"记录(每行一个 模式×声明类型 的结果)。
输出：pair、audit/chunk 与 source document 三个层级的分数文件 + manifest；论文主评估读 source 层。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
import math
from pathlib import Path
from statistics import mean, median
from typing import Any
import unicodedata

try:
    # 进度条；没装 tqdm 就用"原样返回"的替身。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from ..utils.hash import sha256_file, sha256_obj
from ..utils.io import load_yaml, read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger
from ..utils.run_context import git_snapshot
from ..baselines.menta import (
    MENTA_NLI_MODEL_ID,
    MENTA_NLI_REVISION,
    NLIPredictor,
    TransformersNLIPredictor,
    validate_nli_snapshot,
)
from ..parsing.stance_parser import parse_hybrid_response


LOGGER = get_logger(__name__)


HYBRID_PVS_SUPPORT = {"supported": 1.0, "contradicted": 0.0, "insufficient": 0.0}
HYBRID_PVS_VALUE_TEMPLATE = "The corrected value is {value}."


def validate_hybrid_pvs_config(
    config: Mapping[str, Any],
    project_root: str | Path = ".",
) -> dict[str, Any]:
    """复用固定评分配置校验；只返回本地 NLI 参数，不加载模型。"""
    scoring = config.get("scoring") or {}
    expected = {
        "kind": "stance_semantic_restoration",
        "support_mapping": HYBRID_PVS_SUPPORT,
        "pair_formula": "S+ * max(0, R- - A-)",
        "pairs_per_source": 3,
        "source_aggregation": "mean",
        "diagnostic_aggregation": "median",
    }
    for key, value in expected.items():
        if scoring.get(key) != value:
            raise ValueError(f"hybrid_pvs_config_mismatch:{key}")
    restoration = scoring.get("restoration") or {}
    if (restoration.get("kind") != "normalized_exact_then_bidirectional_nli_min"
            or restoration.get("value_template") != HYBRID_PVS_VALUE_TEMPLATE):
        raise ValueError("hybrid_pvs_restoration_config_mismatch")
    settings = restoration.get("nli") or {}
    if (settings.get("model_id") != MENTA_NLI_MODEL_ID
            or settings.get("revision") != MENTA_NLI_REVISION):
        raise ValueError("hybrid_pvs_nli_identity_mismatch")
    device = str(settings.get("device") or "")
    if (settings.get("local_files_only") is not True
            or settings.get("require_cuda") is not True
            or not (device == "cuda" or device.startswith("cuda:"))):
        raise ValueError("hybrid_pvs_requires_local_cuda_nli")
    if not settings.get("snapshot_dir"):
        raise ValueError("hybrid_pvs_nli_snapshot_missing")
    snapshot = Path(settings["snapshot_dir"])
    if not snapshot.is_absolute():
        snapshot = Path(project_root) / snapshot
    return dict(
        snapshot_dir=snapshot.resolve(),
        model_id=settings["model_id"],
        revision=settings["revision"],
        device=device,
        require_cuda=True,
        batch_size=int(settings["batch_size"]),
        max_length=int(settings["max_length"]),
    )


def build_hybrid_pvs_nli(
    config: Mapping[str, Any],
    project_root: str | Path = ".",
) -> NLIPredictor:
    """显式构造固定的本地 NLI；导入评分模块或跑 mock 不会加载模型。"""
    return TransformersNLIPredictor(**validate_hybrid_pvs_config(config, project_root))


def _normalize_hybrid_value(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def semantic_restoration_score(
    correction_entity: str | None,
    original_entity: str,
    *,
    nli: NLIPredictor | None = None,
) -> float:
    """只比较更正值与真实值；完整相等优先，否则取双向蕴含概率的较小值。"""
    if not isinstance(original_entity, str) or not _normalize_hybrid_value(original_entity):
        raise ValueError("hybrid_pvs_original_entity_invalid")
    if correction_entity is None or not correction_entity.strip():
        return 0.0
    if _normalize_hybrid_value(correction_entity) == _normalize_hybrid_value(original_entity):
        return 1.0
    if nli is None:
        raise RuntimeError("hybrid_pvs_nli_required")
    corrected = HYBRID_PVS_VALUE_TEMPLATE.format(value=correction_entity.strip())
    original = HYBRID_PVS_VALUE_TEMPLATE.format(value=original_entity.strip())
    rows = nli.probabilities([(corrected, original), (original, corrected)])
    labels = {"entailment", "neutral", "contradiction"}
    if len(rows) != 2:
        raise ValueError("hybrid_pvs_nli_output_count")
    entailments: list[float] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != labels:
            raise ValueError("hybrid_pvs_nli_labels")
        if any(isinstance(value, bool) for value in row.values()):
            raise ValueError("hybrid_pvs_nli_probabilities")
        values = {label: float(row[label]) for label in labels}
        if (any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values.values())
                or not math.isclose(sum(values.values()), 1.0, abs_tol=1e-5)):
            raise ValueError("hybrid_pvs_nli_probabilities")
        entailments.append(values["entailment"])
    return min(entailments)


def score_hybrid_pair(
    *,
    dataset: str,
    source_key: str,
    pair_id: str,
    original_entity: str,
    plus_response: str | bytes | None,
    minus_response: str | bytes | None,
    nli: NLIPredictor | None = None,
    plus_error: bool = False,
    minus_error: bool = False,
) -> dict[str, Any]:
    """独立的 V24 开发评分接口；只接受原始回答，不读取构造、检索或成员标签。"""
    if any(not isinstance(value, str) or not value.strip() for value in (dataset, source_key, pair_id)):
        raise ValueError("hybrid_pvs_pair_identity_missing")
    if not isinstance(original_entity, str) or not _normalize_hybrid_value(original_entity):
        raise ValueError("hybrid_pvs_original_entity_invalid")
    plus = parse_hybrid_response(plus_response, generator_error=plus_error)
    minus = parse_hybrid_response(minus_response, generator_error=minus_error)
    support = HYBRID_PVS_SUPPORT[plus["stance"]] if plus["parse_status"] == "parsed" else None
    acceptance = HYBRID_PVS_SUPPORT[minus["stance"]] if minus["parse_status"] == "parsed" else None
    result: dict[str, Any] = {
        "dataset": dataset, "source_key": source_key, "pair_id": pair_id,
        "scoring_kind": "stance_semantic_restoration",
        "original_entity": original_entity,
        "plus_response": plus, "minus_response": minus,
        "score_status": "response_error",
        "positive_support": support, "restoration": None,
        "counter_acceptance": acceptance, "restoration_margin": None,
        "non_acceptance": None if acceptance is None else 1.0 - acceptance,
        "pair_pvs": None,
    }
    if support is None or acceptance is None:
        return result
    correction = minus["correction_entity"] if minus["stance"] == "contradicted" else None
    try:
        restoration = semantic_restoration_score(correction, original_entity, nli=nli)
    except Exception as exc:
        # 不把运行失败填为零分，也不回显可能含外部信息的异常正文。
        return {**result, "score_status": "nli_error", "error_type": type(exc).__name__}
    margin = max(0.0, restoration - acceptance)
    return {
        **result, "score_status": "scored", "restoration": restoration,
        "restoration_margin": margin, "pair_pvs": support * margin,
    }


def aggregate_hybrid_source(
    pair_scores: Sequence[Mapping[str, Any]],
    *,
    dataset: str,
    source_key: str,
) -> dict[str, Any]:
    """严格聚合同一 source 的三对；均值是主分，中位数只作诊断。"""
    if len(pair_scores) > 3:
        raise ValueError("hybrid_pvs_pair_budget_exceeded")
    pair_ids: set[str] = set()
    for row in pair_scores:
        if row.get("dataset") != dataset or row.get("source_key") != source_key:
            raise ValueError("hybrid_pvs_source_identity_mismatch")
        pair_id = row.get("pair_id")
        if not isinstance(pair_id, str) or not pair_id.strip() or pair_id in pair_ids:
            raise ValueError("hybrid_pvs_pair_identity_duplicate_or_missing")
        pair_ids.add(pair_id)
        if row.get("scoring_kind") != "stance_semantic_restoration":
            raise ValueError("hybrid_pvs_scoring_kind_mismatch")
        if row.get("score_status") == "scored":
            value = row.get("pair_pvs")
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0.0 <= value <= 1.0):
                raise ValueError("hybrid_pvs_pair_score_invalid")
    result: dict[str, Any] = {
        "dataset": dataset, "source_key": source_key,
        "scoring_kind": "stance_semantic_restoration",
        "pair_scores": [dict(row) for row in pair_scores],
        "score_status": "insufficient_pairs" if len(pair_scores) < 3 else "incomplete",
        "source_pvs": None, "source_pvs_mean": None, "source_pvs_median": None,
    }
    if len(pair_scores) == 3 and all(row.get("score_status") == "scored" for row in pair_scores):
        scores = [float(row["pair_pvs"]) for row in pair_scores]
        result.update(score_status="scored", source_pvs=mean(scores),
                      source_pvs_mean=mean(scores), source_pvs_median=median(scores))
    return result


def prepare_hybrid_pvs_inputs(
    selected_rows: Sequence[Mapping[str, Any]],
    response_rows: Sequence[Mapping[str, Any]],
    *,
    dataset: str,
) -> dict[str, Any]:
    """绑定既有 selected pairs 与 RAG 回答；只适配字段，不重选或重写问句。"""
    sources: dict[str, str] = {}
    wrapped_sources: set[str] = set()
    pairs: list[dict[str, Any]] = []
    pair_ids: set[str] = set()
    identity_fields = ("dataset", "source_key", "chunk_sha256")
    pair_fields = ("pair_id", "original_entity", "counter_entity", "q_plus_text", "q_minus_text")
    for row in selected_rows:
        if not isinstance(row, Mapping):
            raise ValueError("hybrid_pvs_selected_row_invalid")
        construction = row.get("construction", row)
        if not isinstance(construction, Mapping):
            raise ValueError("hybrid_pvs_construction_unavailable")
        if "selected_pairs" in construction:
            selected = construction["selected_pairs"]
            if (not isinstance(selected, list)
                    or construction.get("selected_pair_count", len(selected)) != len(selected)):
                raise ValueError("hybrid_pvs_selected_pair_count_mismatch")
            outer_source = row.get("source", construction)
            if not isinstance(outer_source, Mapping) or any(
                outer_source.get(key) != construction.get(key) for key in identity_fields
            ):
                raise ValueError("hybrid_pvs_construction_source_mismatch")
        else:
            selected = [construction]
        identity = {key: construction.get(key) for key in identity_fields}
        if (identity["dataset"] != dataset
                or any(not isinstance(value, str) or not value.strip() for value in identity.values())):
            raise ValueError("hybrid_pvs_source_identity_invalid")
        source_key, chunk_hash = identity["source_key"], identity["chunk_sha256"]
        if len(chunk_hash) != 64 or any(char not in "0123456789abcdef" for char in chunk_hash):
            raise ValueError("hybrid_pvs_chunk_hash_invalid")
        if source_key in sources and sources[source_key] != chunk_hash:
            raise ValueError("hybrid_pvs_source_chunk_drift")
        if "selected_pairs" in construction:
            if source_key in sources:
                raise ValueError("hybrid_pvs_duplicate_source_result")
            wrapped_sources.add(source_key)
        elif source_key in wrapped_sources:
            raise ValueError("hybrid_pvs_duplicate_source_result")
        sources[source_key] = chunk_hash
        for pair in selected:
            if (not isinstance(pair, Mapping)
                    or any(pair.get(key) != value for key, value in identity.items())
                    or any(not isinstance(pair.get(key), str) or not pair[key].strip() for key in pair_fields)):
                raise ValueError("hybrid_pvs_selected_pair_invalid")
            if pair["pair_id"] in pair_ids:
                raise ValueError("hybrid_pvs_duplicate_selected_pair")
            pair_ids.add(pair["pair_id"])
            pairs.append({**identity, **{key: pair[key] for key in pair_fields}})
    if not sources:
        raise ValueError("hybrid_pvs_selected_input_empty")
    if len(set(sources.values())) != len(sources):
        raise ValueError("hybrid_pvs_chunk_reused_across_sources")
    source_pairs = {key: [pair for pair in pairs if pair["source_key"] == key] for key in sources}
    if any(len(items) > 3 for items in source_pairs.values()):
        raise ValueError("hybrid_pvs_pair_budget_exceeded")

    queries: dict[str, dict[str, Any]] = {}
    for pair in pairs:
        for polarity, claim_type, text_field in (
            ("Q_plus", "true", "q_plus_text"), ("Q_minus", "counterfactual", "q_minus_text"),
        ):
            query_id = sha256_obj({"pair_id": pair["pair_id"], "polarity": polarity})
            queries[query_id] = {
                **{key: pair[key] for key in identity_fields}, "pair_id": pair["pair_id"],
                "query_id": query_id, "polarity": polarity, "claim_type": claim_type,
                "query_text": pair[text_field], "query": pair[text_field],
            }
    responses: dict[str, dict[str, Any]] = {}
    cell: dict[str, Any] | None = None
    fingerprints: set[str] = set()
    cell_fields = ("concrete_model", "retriever_backend", "retriever_id", "variant_id", "context_control")
    for row in response_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("query_id"), str):
            raise ValueError("hybrid_pvs_response_row_invalid")
        query_id = row["query_id"]
        if query_id in responses:
            raise ValueError("hybrid_pvs_duplicate_response")
        query = queries.get(query_id)
        if query is None or any(row.get(key) != query[key] for key in (
            "dataset", "source_key", "pair_id", "claim_type", "query",
        )):
            raise ValueError("hybrid_pvs_response_query_mismatch")
        if "chunk_sha256" in row and row["chunk_sha256"] != query["chunk_sha256"]:
            raise ValueError("hybrid_pvs_response_chunk_mismatch")
        if (row.get("mode") != "rag"
                or any(not isinstance(row.get(key), str) or not row[key].strip() for key in cell_fields)):
            raise ValueError("hybrid_pvs_rag_cell_identity_required")
        if (row.get("error") is not None and not isinstance(row["error"], str)
                or row.get("response") is not None and not isinstance(row["response"], str)):
            raise ValueError("hybrid_pvs_raw_response_invalid")
        current_cell = {key: row.get(key) for key in (*cell_fields, "generator_family", "generator_version")}
        if cell is not None and current_cell != cell:
            raise ValueError("hybrid_pvs_mixed_runtime_cells")
        cell = current_cell
        if row.get("response") and not row.get("error"):
            if row.get("provider_model_id") != row["concrete_model"]:
                raise ValueError("hybrid_pvs_provider_model_mismatch")
            if row.get("system_fingerprint"):
                fingerprints.add(str(row["system_fingerprint"]))
        responses[query_id] = dict(row)
    if len(fingerprints) > 1:
        raise ValueError("hybrid_pvs_mixed_response_fingerprints")
    return {
        "sources": sources, "source_pairs": source_pairs, "pairs": pairs,
        "queries": queries, "responses": responses,
        "cell": None if cell is None else {"mode": "rag", **cell, "system_fingerprints": sorted(fingerprints)},
    }


def run_hybrid_pvs_scoring(
    *,
    dataset: str,
    config_path: str | Path,
    pairs_path: str | Path,
    responses_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    project_root: str | Path = ".",
    dry_run: bool = False,
    run_role: str = "development",
    nli: NLIPredictor | None = None,
) -> dict[str, Any]:
    """V24 离线评分入口；预检不加载模型、不写分数，运行只写全新目录。"""
    root = Path(project_root)
    if run_role not in {"development", "formal"}:
        raise ValueError("hybrid_pvs_run_role_invalid")
    config_file, pairs_file = (root / config_path).resolve(), (root / pairs_path).resolve()
    response_file = None if responses_path is None else (root / responses_path).resolve()
    output = None if output_dir is None else (root / output_dir).resolve()
    if not dry_run and (response_file is None or output is None):
        raise ValueError("hybrid_pvs_responses_and_output_required")
    if not dry_run and output.exists():
        raise FileExistsError("hybrid_pvs_output_exists_use_new_directory")
    config = load_yaml(config_file)
    if config.get("protocol_version") != "pcv-mia-v24" or dataset not in config.get("datasets", []):
        raise ValueError("hybrid_pvs_v24_config_required")
    settings = validate_hybrid_pvs_config(config, root)
    prepared = prepare_hybrid_pvs_inputs(
        list(read_jsonl(pairs_file)), [] if response_file is None else list(read_jsonl(response_file)),
        dataset=dataset,
    )
    snapshot: dict[str, Any]
    try:
        snapshot = {"status": "verified_local_files", **validate_nli_snapshot(
            settings["snapshot_dir"], expected_model_id=settings["model_id"], expected_revision=settings["revision"],
        )}
    except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
        snapshot = {"status": "unavailable", "error_type": type(exc).__name__}
    summary: dict[str, Any] = {
        "run_kind": ("v24_formal_hybrid_pvs" if run_role == "formal" else "v24_development_offline_hybrid_pvs"),
        "protocol_version": "pcv-mia-v24",
        "status": "prepared_inputs_only", "dataset": dataset, "cell": prepared["cell"],
        "source_count": len(prepared["sources"]), "pair_count": len(prepared["pairs"]),
        "query_count": len(prepared["queries"]), "response_count": len(prepared["responses"]),
        "sources_with_three_pairs": sum(len(items) == 3 for items in prepared["source_pairs"].values()),
        "missing_response_count": len(prepared["queries"]) - len(prepared["responses"]),
        "scoring": config["scoring"], "nli_snapshot": snapshot,
        "nli_loaded": nli is not None,
        "cuda_checked": isinstance(nli, TransformersNLIPredictor), "formal_freeze_performed": False,
        "api_calls_performed": 0, "victim_calls_performed": 0, "retriever_calls_performed": 0,
        "config_sha256": sha256_file(config_file), "pairs_sha256": sha256_file(pairs_file),
        "responses_sha256": None if response_file is None else sha256_file(response_file),
        "scorer_sha256": sha256_file(__file__), "git": git_snapshot(),
    }
    if dry_run:
        return summary

    # 先用现有函数处理 exact/缺失等情况；只有非 exact 恢复才需要加载一次 NLI。
    pair_scores: list[dict[str, Any]] = []
    arguments: list[dict[str, Any]] = []
    for pair in prepared["pairs"]:
        bound = []
        for polarity in ("Q_plus", "Q_minus"):
            query_id = sha256_obj({"pair_id": pair["pair_id"], "polarity": polarity})
            bound.append(prepared["responses"].get(query_id, {}))
        arguments.append({
            "dataset": dataset, "source_key": pair["source_key"], "pair_id": pair["pair_id"],
            "original_entity": pair["original_entity"],
            "plus_response": bound[0].get("response"), "minus_response": bound[1].get("response"),
            "plus_error": bool(bound[0].get("error")), "minus_error": bool(bound[1].get("error")),
        })
        pair_scores.append(score_hybrid_pair(**arguments[-1], nli=nli))
    needs_nli = [i for i, score in enumerate(pair_scores) if score["score_status"] == "nli_error"]
    if needs_nli and nli is None:
        nli = build_hybrid_pvs_nli(config, root)
        summary.update(nli_loaded=True, cuda_checked=True)
        for i in needs_nli:
            pair_scores[i] = score_hybrid_pair(**arguments[i], nli=nli)
    for pair, score in zip(prepared["pairs"], pair_scores):
        score.update(chunk_sha256=pair["chunk_sha256"], counter_entity=pair["counter_entity"],
                     q_plus_text=pair["q_plus_text"], q_minus_text=pair["q_minus_text"],
                     **(prepared["cell"] or {}))
    source_scores = [
        {**aggregate_hybrid_source([score for score in pair_scores if score["source_key"] == key],
                                  dataset=dataset, source_key=key), "chunk_sha256": chunk_hash,
         **(prepared["cell"] or {})}
        for key, chunk_hash in prepared["sources"].items()
    ]
    summary.update(
        status="scored" if all(row["score_status"] == "scored" for row in source_scores) else "incomplete",
        scored_pair_count=sum(row["score_status"] == "scored" for row in pair_scores),
        scored_source_count=sum(row["score_status"] == "scored" for row in source_scores),
    )
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in (("pair_scores.jsonl", pair_scores), ("source_scores.jsonl", source_scores)):
        path = output / name
        write_jsonl(rows, path)
        summary[name.removesuffix(".jsonl") + "_sha256"] = sha256_file(path)
    write_json(summary, output / "scoring_summary.json")
    return summary


def support_score(row: dict[str, Any], unknown_lambda: float, refusal_penalty: float) -> float:
    """计算「支持分」：模型对【真实声明 Q+】的态度打分。

    参数:
        row: 一条解析后的态度记录,里面是各种布尔标记(是否支持/反对/不知道...)。
        unknown_lambda: 模型答「不知道」时要扣的分(惩罚系数)。
        refusal_penalty: 模型「拒绝回答」时要扣的分。
    返回:
        分数,大致在 -1.0 ~ 1.0,越高说明模型越支持这条真实声明。
    """
    # 模型明确支持真实声明 → 给满分 1.0
    if row.get("supports_true_claim"):
        return 1.0
    # 模型反对真实声明 → 给 -1.0
    if row.get("rejects_true_claim"):
        return -1.0
    # 模型说「不知道」→ 按 unknown_lambda 扣分
    if row.get("says_unknown"):
        return -float(unknown_lambda)
    # 模型拒绝回答 → 按 refusal_penalty 扣分
    if row.get("refuses"):
        return -float(refusal_penalty)
    # 以上都不是(答非所问/无关)→ 0 分
    return 0.0


def correction_score(row: dict[str, Any], unknown_lambda: float, refusal_penalty: float) -> float:
    """计算「纠正分」：模型对【反事实声明 Q-】的态度打分。

    反事实声明是我们故意伪造的(把真实实体换成假的)。一个真懂文档的系统应该能
    识破并纠正它，所以："纠正回原始实体"得分最高，"识破但没说出正确答案"次之，
    "把伪造的也当真接受"则要扣分。

    参数:
        row: 一条针对反事实声明的态度记录。
        unknown_lambda: 答「不知道」的惩罚系数。
        refusal_penalty: 「拒绝回答」的惩罚系数。
    返回:
        分数(约 -1.0 ~ 1.0),越高说明模型越能识破/纠正伪造声明。
    """
    # 直接把伪造实体纠正回正确的原始实体 → 最强信号,给 1.0
    if row.get("corrects_to_original_entity"):
        return 1.0
    # 识破并否定了伪造声明(但没给出正确值)→ 给 0.5
    if row.get("rejects_counterfactual"):
        return 0.5
    # 把伪造声明当真接受了 → 说明它没真懂,给 -1.0
    if row.get("accepts_counterfactual"):
        return -1.0
    # 说「不知道」→ 按系数扣分
    if row.get("says_unknown"):
        return -float(unknown_lambda)
    # 拒绝回答 → 按系数扣分
    if row.get("refuses"):
        return -float(refusal_penalty)
    # 其它(无关回答)→ 0 分
    return 0.0


def false_acceptance_penalty(row: dict[str, Any], penalty: float) -> float:
    """计算「误受惩罚」：如果模型把伪造声明当真接受了,额外扣的分。

    参数:
        row: 针对反事实声明的态度记录。
        penalty: 误受时扣的分值。
    返回:
        接受了伪造声明则返回 penalty,否则返回 0.0。
    """
    # 仅当模型"接受了反事实(伪造)声明"时才施加这个惩罚。
    return float(penalty) if row.get("accepts_counterfactual") else 0.0


def score_pair(
    plus: dict[str, Any] | None,
    minus: dict[str, Any] | None,
    *,
    unknown_lambda: float,
    refusal_penalty: float,
    false_acceptance_penalty_value: float,
) -> dict[str, Any]:
    """把"一对(Q+ 与 Q-)"的态度合成为这一对的 CVG 分数。

    参数:
        plus:  针对真实声明 Q+ 的态度记录(可能为 None,表示缺这条)。
        minus: 针对反事实声明 Q- 的态度记录(可能为 None)。
        unknown_lambda:                "不知道"的惩罚系数。
        refusal_penalty:               "拒绝"的惩罚系数。
        false_acceptance_penalty_value:"误受伪造"的惩罚分值。
    返回:
        含 support_score / correction_score / false_acceptance_penalty / cvg 的字典。
        其中 cvg = 支持分 + 纠正分 - 误受惩罚。
    """
    # 缺哪一边就给 0 分,保证缺数据时也能稳健计算。
    support = support_score(plus or {}, unknown_lambda, refusal_penalty) if plus else 0.0
    correction = correction_score(minus or {}, unknown_lambda, refusal_penalty) if minus else 0.0
    false_penalty = false_acceptance_penalty(minus or {}, false_acceptance_penalty_value) if minus else 0.0
    return {
        "support_score": support,
        "correction_score": correction,
        "false_acceptance_penalty": false_penalty,
        # 这一对的 CVG = 支持分 + 纠正分 - 误受惩罚。
        "cvg": support + correction - false_penalty,
    }


def compute_pcv_scores(
    dataset: str,
    parsed_stance_path: str | Path,
    output_path: str | Path,
    unknown_lambda: float = 0.5,
    refusal_penalty: float = 0.5,
    false_acceptance_penalty_value: float = 0.0,  # 默认关闭误受项(消融:干净集 AUC≈0.525 无判别力);设 >0 可恢复
    thresholds: list[float] | None = None,
    facts_path: str | Path | None = None,
    benchmark_path: str | Path | None = None,
    queries_path: str | Path | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Aggregate parsed stance rows into document-level PCV scores.

    中文说明：本函数是打分的主入口。它把"逐条态度记录"一步步聚合：
        态度记录 → 按 pair 归拢(把同一对的 RAG/LLM × 真/假 4 条凑齐) → 算每对的 CVG
        → 按 audit_id 聚合出 chunk/audit 诊断分 → 再按 source_key 聚合出论文主分。

    方案 D 的质量加权在这一步生效：每个 fact 带 quality_weight(=可攻击性分)，文档级分数
    输出三个口径，便于交叉验证"加权是否真的有用"：
        pcv_score           RAG-only PVS 简单平均(主分)。
        cg_cvg              RAG - LLM-only 的旧 context-gain 诊断口径。
        pcv_score_context_gain_weighted 旧质量加权 context-gain 诊断口径。
        pcv_score_primary   仅 primary fact 的旧 context-gain 诊断口径。
    若未提供 facts_path，则所有 fact 权重退化为 1.0、tier 视为 primary，三口径都等于简单平均
    ``pcv_score`` 始终是 RAG-only PVS；旧 context-gain 口径仅保留在显式诊断字段中。

    参数:
        dataset:            数据集名。
        parsed_stance_path: 上一步解析出的态度记录文件(jsonl)。
        output_path:        文档级分数的输出路径;同时会派生出 *_pair_scores.jsonl 和 manifest。
        unknown_lambda:     "不知道"的惩罚系数。
        refusal_penalty:    "拒绝"的惩罚系数。
        false_acceptance_penalty_value: "误受伪造"的惩罚分值。
        thresholds:         判定阈值列表;pcv_score 高于阈值则判为成员。默认 [0.3,0.5,0.7,1.0]。
        facts_path:         第 06 步的 facts.jsonl;用于按 fact_id 取 quality_weight/selection_tier。
                            为 None 时退化为不加权(等价旧行为)。
        resume:             断点续跑:结果已存在则跳过。
        force:              强制重算。
    返回:
        manifest(字典):统计信息与产物路径;若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    # 成对分数的输出路径(在主输出名后加 _pair_scores)。
    pair_output = output.with_name(output.stem + "_pair_scores.jsonl")
    source_output = output.with_name(output.stem + "_source_scores.jsonl")
    coverage_output = output.with_name(output.stem + "_source_coverage.jsonl")
    # 断点续跑:结果文件非空且 manifest 存在,就跳过不重算。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        LOGGER.info("Skipping existing PCV scores: %s", output)
        return {"dataset": dataset, "output_path": str(output), "skipped_existing": True}

    # 没给阈值就用一组默认阈值。
    thresholds = thresholds or [0.3, 0.5, 0.7, 1.0]
    # fact_id → (quality_weight, selection_tier)。缺省权重 1.0、tier=primary(等价不加权)。
    fact_weight: dict[str, float] = {}
    fact_tier: dict[str, str] = {}
    fact_source: dict[str, tuple[str, str, str]] = {}
    if facts_path is not None and Path(facts_path).exists():
        for f in read_jsonl(facts_path):
            fid = str(f.get("fact_id"))
            fact_weight[fid] = float(f.get("quality_weight") or 1.0)
            fact_tier[fid] = str(f.get("selection_tier") or "primary")
            fact_source[fid] = (
                str(f.get("source_id") or f.get("doc_id") or f.get("audit_id") or ""),
                str(f.get("source_key") or f.get("source_id") or f.get("doc_id") or f.get("audit_id") or ""),
                str(f.get("doc_id") or ""),
            )
    benchmark_sources: dict[str, dict[str, Any]] = {}
    if benchmark_path is not None and Path(benchmark_path).exists():
        for row in read_jsonl(benchmark_path):
            source_key = str(row.get("source_key") or row.get("source_id") or row.get("audit_id"))
            item = benchmark_sources.setdefault(source_key, {
                "source_key": source_key,
                "source_id": row.get("source_id") or source_key,
                "group": row.get("group"),
                "audit_ids": set(),
            })
            item["audit_ids"].add(str(row.get("audit_id")))

    planned_pairs: dict[str, dict[str, Any]] = {}
    if queries_path is not None and Path(queries_path).exists():
        for row in read_jsonl(queries_path):
            if not row.get("accepted", True):
                continue
            pair_id = str(row.get("pair_id"))
            query_type = str(row.get("query_type") or "default")
            logical_id = f"{pair_id}::{query_type}"
            plan = planned_pairs.setdefault(logical_id, {
                "pair_id": pair_id,
                "query_type": query_type,
                "source_key": str(row.get("source_key") or row.get("source_id") or row.get("audit_id")),
                "source_id": row.get("source_id") or row.get("doc_id"),
                "audit_id": row.get("audit_id"),
                "doc_id": row.get("doc_id"),
                "fact_id": row.get("fact_id"),
                "dataset": row.get("dataset"),
                "group": row.get("group"),
                "claim_types": [],
            })
            plan["claim_types"].append(str(row.get("claim_type")))

    # by_pair: logical pair → { "模式:声明类型" → 态度记录 }；query_type 是 pair 身份的一部分。
    by_pair: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    # pair_meta: 记录每个 pair 的元信息(属于哪份文档、哪个数据集等)。
    pair_meta: dict[str, dict[str, Any]] = {}
    for row in tqdm(read_jsonl(parsed_stance_path), desc="score pcv", unit="stance"):
        pair_id = str(row.get("pair_id"))
        query_type = str(row.get("query_type") or "default")
        logical_id = f"{pair_id}::{query_type}"
        mode = str(row.get("mode"))            # rag 或 llm_only
        claim_type = str(row.get("claim_type"))  # true(真实) 或 counterfactual(反事实)
        # 用"模式:声明类型"作为键,例如 "rag:true"、"llm_only:counterfactual"。
        key = f"{mode}:{claim_type}"
        if key in by_pair[logical_id]:
            raise RuntimeError(f"Duplicate stance cell: logical_pair={logical_id} cell={key}")
        by_pair[logical_id][key] = row
        fid = str(row.get("fact_id"))
        fallback_source = fact_source.get(fid, ("", "", ""))
        pair_meta[logical_id] = {
            "pair_id": pair_id,
            "logical_pair_id": logical_id,
            "query_type": query_type,
            "audit_id": row.get("audit_id"),
            "fact_id": row.get("fact_id"),
            "doc_id": row.get("doc_id") or fallback_source[2],
            "source_id": row.get("source_id") or fallback_source[0] or row.get("doc_id") or row.get("audit_id"),
            "source_key": row.get("source_key") or fallback_source[1] or row.get("source_id") or row.get("doc_id") or row.get("audit_id"),
            "dataset": row.get("dataset"),
            "group": row.get("group"),
            "entity_type": row.get("entity_type"),
        }

    pair_rows: list[dict[str, Any]] = []
    # by_audit: audit_id → 该文档下所有 pair 的分数行,后面用于聚合。
    by_audit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # 逐个 pair 计算 RAG 与 LLM-only 两套 CVG,以及它们的差 CG-CVG。
    complete_pair_ids: set[str] = set()
    all_pair_ids = sorted(set(by_pair) | set(planned_pairs))
    for logical_id in all_pair_ids:
        rows = by_pair.get(logical_id, {})
        meta = pair_meta.get(logical_id) or planned_pairs[logical_id]
        planned_claims = planned_pairs.get(logical_id, {}).get("claim_types", ["true", "counterfactual"])
        plan_complete = sorted(planned_claims) == ["counterfactual", "true"]
        rag_complete = plan_complete and "rag:true" in rows and "rag:counterfactual" in rows
        llm_complete = "llm_only:true" in rows and "llm_only:counterfactual" in rows
        if not rag_complete:
            pair_rows.append({
                **meta,
                "complete_rag_pair": False,
                "complete_llm_pair": llm_complete,
                "status": "incomplete_rag_pair" if plan_complete else "invalid_query_pair",
                "cvg_rag": None,
                "cvg_llm": None,
                "cg_cvg": None,
            })
            continue
        # RAG 模式:用 rag:true(真实) 和 rag:counterfactual(反事实) 两条算 CVG。
        rag = score_pair(
            rows.get("rag:true"),
            rows.get("rag:counterfactual"),
            unknown_lambda=unknown_lambda,
            refusal_penalty=refusal_penalty,
            false_acceptance_penalty_value=false_acceptance_penalty_value,
        )
        # LLM-only 模式:同理用纯模型的两条记录。
        llm = (
            score_pair(
                rows.get("llm_only:true"),
                rows.get("llm_only:counterfactual"),
                unknown_lambda=unknown_lambda,
                refusal_penalty=refusal_penalty,
                false_acceptance_penalty_value=false_acceptance_penalty_value,
            )
            if llm_complete
            else None
        )
        fid = str(meta.get("fact_id"))
        out = {
            **meta,
            "complete_rag_pair": True,
            "complete_llm_pair": llm_complete,
            "status": "complete",
            "attribution_status": "available" if llm_complete else "unavailable",
            "cvg_rag": rag["cvg"],
            "cvg_llm": llm["cvg"] if llm is not None else None,
            # 核心信号:检索带来的增益 = RAG 的 CVG 减去纯模型的 CVG。
            "cg_cvg": rag["cvg"] - llm["cvg"] if llm is not None else None,
            # 这一对所属 fact 的质量权重与分层(方案 D)。
            "quality_weight": fact_weight.get(fid, 1.0),
            "selection_tier": fact_tier.get(fid, "primary"),
            "support_score_rag": rag["support_score"],
            "correction_score_rag": rag["correction_score"],
            "false_acceptance_penalty_rag": rag["false_acceptance_penalty"],
            "support_score_llm": llm["support_score"] if llm is not None else None,
            "correction_score_llm": llm["correction_score"] if llm is not None else None,
            "false_acceptance_penalty_llm": llm["false_acceptance_penalty"] if llm is not None else None,
            # 下面这些布尔字段用于后续"机制分析",记录关键事件是否发生。
            "support_true_rag": bool(rows.get("rag:true", {}).get("supports_true_claim")),
            "correct_counterfactual_rag": bool(rows.get("rag:counterfactual", {}).get("corrects_to_original_entity")),
            "accept_false_rag": bool(rows.get("rag:counterfactual", {}).get("accepts_counterfactual")),
            "unknown_rag": bool(rows.get("rag:true", {}).get("says_unknown")) or bool(rows.get("rag:counterfactual", {}).get("says_unknown")),
            "unknown_llm": bool(rows.get("llm_only:true", {}).get("says_unknown")) or bool(rows.get("llm_only:counterfactual", {}).get("says_unknown")),
        }
        pair_rows.append(out)
        complete_pair_ids.add(logical_id)
        # 把这对的结果挂到它所属的文档(audit_id)名下。
        by_audit[str(meta["audit_id"])].append(out)

    score_rows: list[dict[str, Any]] = []
    # 把同一份文档下的多对分数聚合,得到该文档的最终成员分(三口径)。
    for audit_id, rows in sorted(by_audit.items()):
        # 不加权简单平均(旧口径,保留)。
        cvg_rag = mean([float(r["cvg_rag"]) for r in rows]) if rows else 0.0
        attribution_available = bool(rows) and all(r.get("attribution_status") == "available" for r in rows)
        cvg_llm = mean([float(r["cvg_llm"]) for r in rows]) if attribution_available else None
        cg_list = [float(r["cg_cvg"]) for r in rows] if attribution_available else []
        cg_cvg = mean(cg_list) if cg_list else None
        # 旧质量加权 context-gain 口径，保留用于消融，不再作为 P0 主分。
        weights = [max(0.0, float(r.get("quality_weight", 1.0))) for r in rows]
        wsum = sum(weights)
        pcv_score_context_gain_weighted = (
            sum(w * c for w, c in zip(weights, cg_list)) / wsum
        ) if attribution_available and wsum > 0 else None
        # 仅 primary 口径:只用高质量 fact;没有 primary 则退回全体简单平均。
        primary_cg = [c for r, c in zip(rows, cg_list) if str(r.get("selection_tier")) == "primary"]
        pcv_score_primary = mean(primary_cg) if primary_cg else cg_cvg
        num_primary = sum(1 for r in rows if str(r.get("selection_tier")) == "primary")
        # per-term 去偏 + 门控信号(消融发现先验泄漏只在 correction 项,support 几乎不漏):
        #   correction_llm = LLM-only 对反事实的纠正程度,是"该样本是否已被 LLM 知道"的污染门控信号。
        #   cvg_debiased = sup_rag + (cor_rag - cor_llm):只扣有泄漏的 correction 项、不动干净的 support,
        #   比整体减 cg_cvg 去偏更准(详见消融)。cvg_rag 本身不变,这是旁加的新终分。
        correction_llm = (
            mean([float(r["correction_score_llm"]) for r in rows])
            if attribution_available
            else None
        )
        cvg_debiased = mean(
            [
                float(r.get("support_score_rag", 0.0))
                + float(r.get("correction_score_rag", 0.0))
                - float(r.get("correction_score_llm", 0.0))
                for r in rows
            ]
        ) if attribution_available else None
        row = {
            "audit_id": audit_id,
            "doc_id": rows[0].get("doc_id"),
            "source_id": rows[0].get("source_id") or rows[0].get("doc_id") or audit_id,
            "source_key": rows[0].get("source_key") or rows[0].get("source_id") or rows[0].get("doc_id") or audit_id,
            "dataset": rows[0].get("dataset"),
            "group": rows[0].get("group"),
            "num_pairs": len(rows),
            "num_primary_pairs": num_primary,
            "attribution_status": "available" if attribution_available else "unavailable",
            "cvg_rag": cvg_rag,
            "cvg_llm": cvg_llm,
            "correction_llm": correction_llm,    # 门控信号:LLM-only 对反事实的纠正(污染/先验指标)
            "cg_cvg": cg_cvg,
            "cvg_debiased": cvg_debiased,         # per-term 去偏终分:sup_rag+(cor_rag-cor_llm)
            # P0 主分：严格黑盒 RAG-only Paired Verification Score。
            "pvs_rag": cvg_rag,
            "pcv_score": cvg_rag,
            # P0 前的质量加权 context-gain 分数，显式保留为诊断字段。
            "pcv_score_context_gain_weighted": pcv_score_context_gain_weighted,
            # 仅用 primary(高质量)fact 的口径,用于交叉验证 fallback 是否在害结果。
            "pcv_score_primary": pcv_score_primary,
            # 统计该文档中各类关键事件发生的次数/比例,供机制分析使用。
            "support_true_count_rag": sum(1 for r in rows if r.get("support_true_rag")),
            "correct_counterfactual_count_rag": sum(1 for r in rows if r.get("correct_counterfactual_rag")),
            "accept_false_count_rag": sum(1 for r in rows if r.get("accept_false_rag")),
            # 比例 = 次数 / 总对数;用 max(1, ...) 防止除以 0。
            "unknown_rate_rag": sum(1 for r in rows if r.get("unknown_rag")) / max(1, len(rows)),
            "unknown_rate_llm": (
                sum(1 for r in rows if r.get("unknown_llm")) / max(1, len(rows))
                if attribution_available
                else None
            ),
        }
        # 对每个阈值记录 RAG-only 主分的历史固定阈值判断，仅供诊断。
        for threshold in thresholds:
            row[f"predicted_member_t{threshold}"] = bool(cvg_rag >= threshold)
        score_rows.append(row)

    # P0-2：同一 source 的多个 audit/chunk 先各自等权，再聚合为一篇 source 一行的论文主分。
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in score_rows:
        by_source[str(row.get("source_key") or row.get("source_id") or row.get("audit_id"))].append(row)
    facts_sources = {source[1] for source in fact_source.values() if source[1]}
    if not benchmark_sources:
        for source_key, rows in by_source.items():
            benchmark_sources[source_key] = {
                "source_key": source_key,
                "source_id": rows[0].get("source_id") or source_key,
                "group": rows[0].get("group"),
                "audit_ids": {str(r.get("audit_id")) for r in rows},
            }
    planned_by_source: dict[str, set[str]] = defaultdict(set)
    for logical_id, plan in planned_pairs.items():
        planned_by_source[str(plan.get("source_key"))].add(logical_id)
    if not planned_pairs:
        for logical_id, meta in pair_meta.items():
            planned_by_source[str(meta.get("source_key"))].add(logical_id)

    coverage_rows: list[dict[str, Any]] = []
    eligible_sources: set[str] = set()
    for source_key, meta in sorted(benchmark_sources.items()):
        planned = planned_by_source.get(source_key, set())
        complete = planned & complete_pair_ids
        reasons: list[str] = []
        if facts_path is not None and source_key not in facts_sources:
            reasons.append("no_fact")
        if not planned:
            reasons.append("no_accepted_pair")
        attack_eligible = bool(planned) and not (facts_path is not None and source_key not in facts_sources)
        execution_complete = not attack_eligible or len(complete) == len(planned)
        if attack_eligible and not execution_complete:
            reasons.append("incomplete_rag_pair")
        eligible = attack_eligible and execution_complete
        if eligible:
            eligible_sources.add(source_key)
        coverage_rows.append({
            "source_key": source_key,
            "source_id": meta.get("source_id") or source_key,
            "dataset": dataset,
            "group": meta.get("group"),
            "planned_chunks": len(meta.get("audit_ids") or []),
            "planned_pairs": len(planned),
            "complete_rag_pairs": len(complete),
            "attack_eligible": attack_eligible,
            "execution_complete": execution_complete,
            "evaluation_eligible": eligible,
            "status": "complete" if eligible else "excluded",
            "reasons": reasons,
        })

    source_rows: list[dict[str, Any]] = []
    for source_key, rows in sorted(by_source.items()):
        if source_key not in eligible_sources:
            continue
        groups = {str(r.get("group")) for r in rows}
        if len(groups) != 1:
            raise RuntimeError(f"Source crosses score groups: source_key={source_key} groups={sorted(groups)}")
        source_row = {
            "source_key": source_key,
            "source_id": rows[0].get("source_id") or source_key,
            "dataset": rows[0].get("dataset"),
            "group": rows[0].get("group"),
            "num_chunks": len(rows),
            "num_pairs": sum(int(r.get("num_pairs", 0)) for r in rows),
            "audit_ids": [r.get("audit_id") for r in rows],
            "doc_ids": [r.get("doc_id") for r in rows],
            "pvs_rag": mean(float(r.get("pvs_rag", r.get("cvg_rag", 0.0))) for r in rows),
            "pcv_score": mean(float(r.get("pcv_score", r.get("cvg_rag", 0.0))) for r in rows),
            "cvg_rag": mean(float(r.get("cvg_rag", 0.0)) for r in rows),
            "attribution_status": (
                "available" if all(r.get("attribution_status") == "available" for r in rows) else "unavailable"
            ),
            "cvg_llm": (
                mean(float(r["cvg_llm"]) for r in rows)
                if all(r.get("attribution_status") == "available" for r in rows)
                else None
            ),
            "cg_cvg": (
                mean(float(r["cg_cvg"]) for r in rows)
                if all(r.get("attribution_status") == "available" for r in rows)
                else None
            ),
            "pcv_score_context_gain_weighted": (
                mean(float(r["pcv_score_context_gain_weighted"]) for r in rows)
                if all(r.get("attribution_status") == "available" for r in rows)
                else None
            ),
        }
        for threshold in thresholds:
            source_row[f"predicted_member_t{threshold}"] = bool(source_row["pcv_score"] >= threshold)
        source_rows.append(source_row)

    # 写出成对分数与文档级分数两个文件。
    write_jsonl(pair_rows, pair_output)
    write_jsonl(score_rows, output)
    write_jsonl(source_rows, source_output)
    write_jsonl(coverage_rows, coverage_output)
    manifest = {
        "dataset": dataset,
        "output_path": str(output),
        "pair_scores_path": str(pair_output),
        "source_scores_path": str(source_output),
        "source_coverage_path": str(coverage_output),
        "pairs": len(pair_rows),
        "scored_samples": len(score_rows),
        "scored_sources": len(source_rows),
        "planned_sources": len(coverage_rows),
        "incomplete_pairs": sum(1 for row in pair_rows if not row.get("complete_rag_pair")),
        "excluded_sources": sum(1 for row in coverage_rows if not row.get("evaluation_eligible")),
        "coverage_by_group": {
            group: {
                "planned": sum(1 for row in coverage_rows if row.get("group") == group),
                "attack_eligible": sum(1 for row in coverage_rows if row.get("group") == group and row.get("attack_eligible")),
                "eligible": sum(1 for row in coverage_rows if row.get("group") == group and row.get("evaluation_eligible")),
            }
            for group in sorted({str(row.get("group")) for row in coverage_rows})
        },
        "source_counts_by_group": {
            group: sum(1 for row in source_rows if row.get("group") == group)
            for group in sorted({str(row.get("group")) for row in source_rows})
        },
        "main_score_key": "pcv_score",
        "main_score_definition": "source mean of RAG-only paired verification score",
        "attribution_status": (
            "available" if source_rows and all(row.get("attribution_status") == "available" for row in source_rows)
            else "unavailable"
        ),
        "weighted": bool(fact_weight),
        "facts_path": str(facts_path) if facts_path is not None else None,
        "unknown_lambda": unknown_lambda,
        "refusal_penalty": refusal_penalty,
        "false_acceptance_penalty": false_acceptance_penalty_value,
        "thresholds": thresholds,
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Computed PCV scores: samples=%s pairs=%s weighted=%s", len(score_rows), len(pair_rows), bool(fact_weight))
    return manifest
