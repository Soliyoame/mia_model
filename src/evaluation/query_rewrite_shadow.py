"""Shadow non-inferiority gate for the diverse slotted-query protocol."""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Sequence

from ..utils.hash import sha256_file, sha256_obj
from ..utils.io import read_json, read_jsonl, write_json


LEGACY_VARIANT = "legacy_literal_verification"
NEW_VARIANT = "diverse_slotted_verification"
REQUIRED_RETRIEVERS = frozenset({"BGE", "BM25", "hybrid"})
EXPECTED_VICTIM_GENERATOR = "meta/llama-3.1-70b-instruct"
EXPECTED_RAG_RETRIEVER = "BGE"


def binary_auc(labels: Sequence[int], scores: Sequence[float]) -> float:
    """计算含并列分数 0.5 修正的二分类 AUC。"""

    if len(labels) != len(scores) or not labels:
        raise ValueError("AUC labels and scores must have the same non-zero length")
    positives = [float(score) for label, score in zip(labels, scores, strict=True) if label == 1]
    negatives = [float(score) for label, score in zip(labels, scores, strict=True) if label == 0]
    if not positives or not negatives:
        raise ValueError("AUC requires both member and non-member sources")
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return wins / (len(positives) * len(negatives))


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("Quantile requires at least one value")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def validate_shadow_sources(
    rows: Iterable[dict[str, Any]],
    *,
    datasets: Sequence[str],
    members_per_dataset: int = 100,
    non_members_per_dataset: int = 100,
) -> dict[str, Any]:
    """验证 shadow source 固定预算、canonical 隔离和近重复排除标记。"""

    materialized = list(rows)
    seen: set[tuple[str, str]] = set()
    counts: Counter[tuple[str, int]] = Counter()
    for row in materialized:
        dataset = str(row.get("dataset") or "")
        source_key = str(row.get("source_key") or "")
        label = int(row.get("label"))
        if dataset not in datasets or label not in {0, 1} or not source_key:
            raise RuntimeError(f"Invalid shadow source row: {row}")
        identity = (dataset, source_key)
        if identity in seen:
            raise RuntimeError(f"Duplicate shadow source: {identity}")
        seen.add(identity)
        if bool(row.get("entered_canonical")):
            raise RuntimeError(f"Shadow source entered canonical artifacts: {identity}")
        if bool(row.get("near_duplicate_of_formal")):
            raise RuntimeError(f"Shadow source is a formal near-duplicate: {identity}")
        if not str(row.get("text_hash") or ""):
            raise RuntimeError(f"Shadow source lacks frozen text_hash: {identity}")
        counts[(dataset, label)] += 1
    expected = {
        (dataset, label): members_per_dataset if label == 1 else non_members_per_dataset
        for dataset in datasets
        for label in (0, 1)
    }
    if dict(counts) != expected:
        raise RuntimeError(f"Shadow source budget mismatch: expected={expected}, actual={dict(counts)}")
    return {
        "sources": len(materialized),
        "counts": {f"{dataset}:{label}": count for (dataset, label), count in sorted(counts.items())},
        "source_plan_hash": sha256_obj(sorted(materialized, key=lambda row: (row["dataset"], row["source_key"]))),
    }


def _score_maps(
    rows: Sequence[dict[str, Any]],
    datasets: Sequence[str],
) -> dict[str, dict[str, dict[str, tuple[int, float]]]]:
    maps: dict[str, dict[str, dict[str, tuple[int, float]]]] = {
        variant: {dataset: {} for dataset in datasets}
        for variant in (LEGACY_VARIANT, NEW_VARIANT)
    }
    for row in rows:
        variant = str(row.get("variant") or "")
        dataset = str(row.get("dataset") or "")
        source_key = str(row.get("source_key") or "")
        if variant not in maps or dataset not in maps[variant] or not source_key:
            raise RuntimeError(f"Unexpected shadow score identity: {row}")
        if source_key in maps[variant][dataset]:
            raise RuntimeError(f"Duplicate shadow source score: {variant}/{dataset}/{source_key}")
        label = int(row.get("label"))
        if label not in {0, 1}:
            raise RuntimeError(f"Invalid shadow membership label: {row}")
        maps[variant][dataset][source_key] = (label, float(row["score"]))
    for dataset in datasets:
        legacy_keys = set(maps[LEGACY_VARIANT][dataset])
        new_keys = set(maps[NEW_VARIANT][dataset])
        if legacy_keys != new_keys or not legacy_keys:
            raise RuntimeError(f"Legacy/new shadow score sources differ for {dataset}")
        for source_key in legacy_keys:
            if maps[LEGACY_VARIANT][dataset][source_key][0] != maps[NEW_VARIANT][dataset][source_key][0]:
                raise RuntimeError(f"Legacy/new label mismatch: {dataset}/{source_key}")
    return maps


def source_bootstrap_auc_difference(
    score_rows: Sequence[dict[str, Any]],
    *,
    datasets: Sequence[str],
    iterations: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """对匹配 source 重采样，估计新旧 macro AUC 差值置信下界。"""

    if iterations < 100:
        raise ValueError("Source bootstrap requires at least 100 iterations")
    maps = _score_maps(score_rows, datasets)
    aucs: dict[str, dict[str, float]] = {variant: {} for variant in maps}
    for variant in maps:
        for dataset in datasets:
            values = list(maps[variant][dataset].values())
            aucs[variant][dataset] = binary_auc(
                [label for label, _ in values],
                [score for _, score in values],
            )
    point_differences = {
        dataset: aucs[NEW_VARIANT][dataset] - aucs[LEGACY_VARIANT][dataset]
        for dataset in datasets
    }
    rng = random.Random(seed)
    macro_differences: list[float] = []
    for _ in range(iterations):
        dataset_differences: list[float] = []
        for dataset in datasets:
            source_keys = sorted(maps[LEGACY_VARIANT][dataset])
            sampled_keys = [rng.choice(source_keys) for _ in source_keys]
            labels = [maps[LEGACY_VARIANT][dataset][key][0] for key in sampled_keys]
            if len(set(labels)) < 2:
                continue
            legacy_auc = binary_auc(
                labels,
                [maps[LEGACY_VARIANT][dataset][key][1] for key in sampled_keys],
            )
            new_auc = binary_auc(
                labels,
                [maps[NEW_VARIANT][dataset][key][1] for key in sampled_keys],
            )
            dataset_differences.append(new_auc - legacy_auc)
        if len(dataset_differences) == len(datasets):
            macro_differences.append(sum(dataset_differences) / len(dataset_differences))
    if len(macro_differences) < int(iterations * 0.95):
        raise RuntimeError("Too many invalid source-bootstrap resamples")
    return {
        "auc": aucs,
        "dataset_point_differences": point_differences,
        "macro_point_difference": sum(point_differences.values()) / len(point_differences),
        "macro_difference_ci95": [
            _quantile(macro_differences, 0.025),
            _quantile(macro_differences, 0.975),
        ],
        "iterations": iterations,
        "seed": seed,
    }


def evaluate_query_rewrite_shadow(
    *,
    score_rows: Sequence[dict[str, Any]],
    retrieval_rows: Sequence[dict[str, Any]],
    lexical_rows: Sequence[dict[str, Any]],
    audit: dict[str, Any],
    datasets: Sequence[str] = ("enron", "edgar", "pubmed"),
    bootstrap_iterations: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """汇总全部晋升门禁；任一失败均返回 passed=false。"""

    auc = source_bootstrap_auc_difference(
        score_rows,
        datasets=datasets,
        iterations=bootstrap_iterations,
        seed=seed,
    )
    failures: list[str] = []
    if float(auc["macro_difference_ci95"][0]) < -0.01:
        failures.append("macro_auc_ci_lower_bound")
    for dataset, difference in auc["dataset_point_differences"].items():
        if float(difference) < -0.03:
            failures.append(f"dataset_auc_drop:{dataset}")

    retrieval_groups: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in retrieval_rows:
        key = (
            str(row.get("variant") or ""),
            str(row.get("dataset") or ""),
            str(row.get("retriever") or ""),
        )
        retrieval_groups[key].append(float(row["target_hit_at_5"]))
    retrieval_summary: dict[str, Any] = {}
    for dataset in datasets:
        for retriever in sorted(REQUIRED_RETRIEVERS):
            old_values = retrieval_groups.get((LEGACY_VARIANT, dataset, retriever), [])
            new_values = retrieval_groups.get((NEW_VARIANT, dataset, retriever), [])
            if not old_values or len(old_values) != len(new_values):
                failures.append(f"retrieval_rows_missing:{dataset}:{retriever}")
                continue
            old_recall = sum(old_values) / len(old_values)
            new_recall = sum(new_values) / len(new_values)
            difference = new_recall - old_recall
            retrieval_summary[f"{dataset}:{retriever}"] = {
                "legacy_recall_at_5": old_recall,
                "new_recall_at_5": new_recall,
                "difference": difference,
            }
            if difference < -0.02:
                failures.append(f"recall_at_5_drop:{dataset}:{retriever}")

    lexical_groups: dict[str, list[float]] = defaultdict(list)
    for row in lexical_rows:
        lexical_groups[str(row.get("variant") or "")].append(
            float(row["five_gram_containment"])
        )
    if not lexical_groups[LEGACY_VARIANT] or not lexical_groups[NEW_VARIANT]:
        failures.append("lexical_rows_missing")
        lexical_summary: dict[str, Any] = {}
    else:
        old_median = median(lexical_groups[LEGACY_VARIANT])
        new_median = median(lexical_groups[NEW_VARIANT])
        reduction = 1.0 - (new_median / old_median) if old_median > 0 else 0.0
        lexical_summary = {
            "legacy_median": old_median,
            "new_median": new_median,
            "relative_reduction": reduction,
        }
        if old_median <= 0 or new_median > old_median * 0.5:
            failures.append("five_gram_median_reduction")

    required_audit_flags = (
        "fixed_budget_pass",
        "structure_gate_pass",
        "naturalness_gate_pass",
        "semantic_gate_pass",
        "diversity_gate_pass",
        "formal_near_duplicate_exclusion_pass",
    )
    for flag in required_audit_flags:
        if audit.get(flag) is not True:
            failures.append(f"audit:{flag}")
    if int(audit.get("logical_victim_calls") or 0) != 7200:
        failures.append("audit:logical_victim_calls")
    if str(audit.get("victim_generator") or "") != EXPECTED_VICTIM_GENERATOR:
        failures.append("audit:victim_generator")
    if str(audit.get("rag_retriever") or "") != EXPECTED_RAG_RETRIEVER:
        failures.append("audit:rag_retriever")
    if set(audit.get("variants") or []) != {LEGACY_VARIANT, NEW_VARIANT}:
        failures.append("audit:variants")
    if set(audit.get("retrievers") or []) != REQUIRED_RETRIEVERS:
        failures.append("audit:retrievers")
    if bool(audit.get("neutral_prompt_robustness_cell")):
        failures.append("audit:neutral_prompt_robustness_cell_forbidden")

    return {
        "passed": not failures,
        "failures": failures,
        "auc_noninferiority": auc,
        "retrieval": retrieval_summary,
        "lexical": lexical_summary,
        "audit": audit,
        "gate_protocol": "diverse_query_shadow_noninferiority_v1",
    }


def evaluate_query_rewrite_shadow_files(
    *,
    sources_path: str | Path,
    scores_path: str | Path,
    retrieval_path: str | Path,
    lexical_path: str | Path,
    audit_path: str | Path,
    output_path: str | Path,
    datasets: Sequence[str] = ("enron", "edgar", "pubmed"),
    bootstrap_iterations: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """文件入口，并把输入 hash 与 gate 结果一起冻结。"""

    source_rows = list(read_jsonl(sources_path))
    source_plan = validate_shadow_sources(
        source_rows,
        datasets=datasets,
        members_per_dataset=100,
        non_members_per_dataset=100,
    )
    derived_calls = int(source_plan["sources"]) * 3 * 2 * 2
    score_rows = list(read_jsonl(scores_path))
    expected_sources = {
        (str(row["dataset"]), str(row["source_key"])) for row in source_rows
    }
    for variant in (LEGACY_VARIANT, NEW_VARIANT):
        scored_sources = {
            (str(row.get("dataset") or ""), str(row.get("source_key") or ""))
            for row in score_rows
            if str(row.get("variant") or "") == variant
        }
        if scored_sources != expected_sources:
            raise RuntimeError(f"Shadow score/source plan mismatch for {variant}")
    result = evaluate_query_rewrite_shadow(
        score_rows=score_rows,
        retrieval_rows=list(read_jsonl(retrieval_path)),
        lexical_rows=list(read_jsonl(lexical_path)),
        audit=read_json(audit_path),
        datasets=datasets,
        bootstrap_iterations=bootstrap_iterations,
        seed=seed,
    )
    if int((result.get("audit") or {}).get("logical_victim_calls") or 0) != derived_calls:
        raise RuntimeError("Shadow audit victim-call budget does not match the frozen source plan")
    result["source_plan"] = source_plan
    result["derived_logical_victim_calls"] = derived_calls
    result["input_hashes"] = {
        "sources": sha256_file(sources_path),
        "scores": sha256_file(scores_path),
        "retrieval": sha256_file(retrieval_path),
        "lexical": sha256_file(lexical_path),
        "audit": sha256_file(audit_path),
    }
    result["gate_identity_hash"] = sha256_obj(
        {
            "protocol": result["gate_protocol"],
            "input_hashes": result["input_hashes"],
            "datasets": list(datasets),
            "bootstrap_iterations": bootstrap_iterations,
            "seed": seed,
        }
    )
    write_json(result, output_path)
    if not result["passed"]:
        raise RuntimeError(f"Diverse query shadow promotion gate failed: {result['failures']}")
    return result
