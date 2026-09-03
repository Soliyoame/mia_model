"""v24 pre-split eligibility checks and bounded development canaries.

The canary is deliberately membership blind.  It may call only the configured
Luna sibling model; Retriever, victim, membership and AUC are never loaded.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from collections.abc import Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.restoration_first_v24 import (  # noqa: E402
    build_luna_candidate_provider,
    build_v24_semantic_similarity,
    enumerate_candidate_facts,
    get_max_candidate_facts_per_source,
    iter_frozen_source_pool,
    load_v24_config,
    scan_until_target,
    screen_source,
    source_pool_bindings,
    validate_eligibility_manifest,
    validate_split_manifest,
)
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import read_json, read_jsonl, write_json, write_jsonl  # noqa: E402


CANARY_OUTPUT_DIR = Path("artifacts/v24/development/query_quality_canary_r1")
CAPACITY_OUTPUT_DIR = Path("artifacts/v24/development/capacity_check_r1")


def _membership_blind_fact(row: Mapping[str, object], source: Mapping[str, object]) -> dict[str, object]:
    """Project an old canary row onto the minimal v24 fact contract."""

    forbidden = {
        "effective_type",
        "counterfactual_entity",
        "counterfactual_claim",
        "membership",
        "membership_label",
        "group",
        "retriever_output",
        "retrieval_score",
        "victim_response",
        "attack_score",
        "attack_auc",
        "auc",
    }
    if forbidden.intersection(row):
        # These fields are intentionally ignored rather than copied.  The
        # source canary is legacy-shaped, but the v24 construction input is not.
        pass
    source_text = str(source.get("full_text") or "")
    claim = str(row.get("true_claim") or "").strip()
    original = str(row.get("original_entity") or "").strip()
    if not claim or not original or source_text.find(claim) < 0:
        raise ValueError("v24_canary_fact_not_source_grounded")
    claim_offset = source_text.find(claim)
    local_offset = claim.find(original)
    if local_offset < 0:
        raise ValueError("v24_canary_original_not_in_true_claim")
    identity = {
        "dataset": str(source.get("dataset") or row.get("dataset") or ""),
        "source_key": str(source.get("source_key") or row.get("source_key") or ""),
        "source_order_rank": str(source.get("source_order_rank") or ""),
        "full_text": source_text,
    }
    from src.prepare.restoration_first_v24 import _source_identity, _mask_entity_mentions

    source_identity = _source_identity(identity)
    return {
        **source_identity,
        "upstream_pair_id": str(row.get("upstream_pair_id") or row.get("pair_id") or sha256_obj({
            "dataset": identity["dataset"],
            "source_key": identity["source_key"],
            "claim": claim,
            "original": original,
        })),
        "true_claim": claim,
        "original_entity": original,
        "original_span": [claim_offset + local_offset, claim_offset + local_offset + len(original)],
        "proposition_span": [claim_offset, claim_offset + len(claim)],
        "slotted_true_claim": _mask_entity_mentions(claim, original),
        "fact_order": int(row.get("canary_pair_index", 0) or 0),
    }


def _load_canary_inputs(root: Path, path: str | Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for row in read_jsonl(root / path):
        # Explicit projection makes legacy fields impossible to enter the Luna prompt.
        records.append({
            key: row[key]
            for key in ("source_key", "dataset", "true_claim", "original_entity", "original_span", "pair_id", "canary_pair_index")
            if key in row
        })
    return records


def _source_lookup(root: Path, datasets: set[str], source_keys: set[str]) -> dict[str, dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    for dataset in sorted(datasets):
        for source in iter_frozen_source_pool(root, dataset):
            key = str(source.get("source_key") or "")
            if key in source_keys:
                found[key] = source
                if len(found) == len(source_keys):
                    return found
    missing = sorted(source_keys - set(found))
    if missing:
        raise RuntimeError(f"v24_canary_source_missing:{missing[:3]}")
    return found


def run_canary(root: Path, *, input_path: str | Path, output_dir: str | Path) -> dict[str, object]:
    config = load_v24_config(root)
    inputs = _load_canary_inputs(root, input_path)
    expected = int(config.get("development", {}).get("canary_pair_count", 30))
    correction_retries = int(config.get("eligibility", {}).get("semantic_correction_retries", 1))
    fact_budget = get_max_candidate_facts_per_source(config)
    if len(inputs) != expected:
        raise ValueError(f"v24_canary_input_count:{len(inputs)}:{expected}")
    sources = _source_lookup(root, {str(row.get("dataset") or "") for row in inputs}, {str(row.get("source_key") or "") for row in inputs})
    semantic_scorer = build_v24_semantic_similarity(root)
    provider = build_luna_candidate_provider(root)
    results: list[dict[str, object]] = []
    try:
        for row in inputs:
            try:
                source = sources[str(row["source_key"])]
                fact = _membership_blind_fact(row, source)
                screened = screen_source(
                    source,
                    candidate_provider=provider,
                    facts=[fact],
                    minimum_pairs=1,
                    allow_surface_fallback=False,
                    similarity_fn=semantic_scorer,
                    semantic_correction_retries=correction_retries,
                    include_candidate_evidence=True,
                    max_candidate_facts_per_source=fact_budget,
                )
                selected = screened.get("selected_pairs") or []
                results.append({
                    "canary_pair_index": row.get("canary_pair_index"),
                    "dataset": fact["dataset"],
                    "source_key": fact["source_key"],
                    "upstream_pair_id": fact["upstream_pair_id"],
                    "eligible": bool(screened.get("eligible")),
                    "selected_pair": selected[0] if selected else None,
                    "rejection_reason_counts": screened.get("rejection_reason_counts", {}),
                    "candidate_evidence": screened.get("candidate_evidence", []),
                })
            except Exception as exc:
                # Preserve per-pair failure evidence before the aggregate canary
                # status is decided.  Error text is intentionally secret-free.
                results.append({
                    "canary_pair_index": row.get("canary_pair_index"),
                    "dataset": row.get("dataset"),
                    "source_key": row.get("source_key"),
                    "upstream_pair_id": row.get("pair_id"),
                    "eligible": False,
                    "selected_pair": None,
                    "candidate_evidence": [],
                    "rejection_reason_counts": {
                        f"execution_error:{type(exc).__name__}:{exc}": 1,
                    },
                })
    finally:
        semantic_scorer.close()
    passed = sum(bool(item["eligible"]) for item in results)
    output = root / output_dir
    write_jsonl(results, output / "canary_results.jsonl")
    summary = {
        "status": "passed" if passed == expected else "failed_hard_gates",
        "protocol_version": config["protocol_version"],
        "canary_pair_count": expected,
        "passed_pair_count": passed,
        "fallback_pair_count": 0,
        "fallback_allowed": False,
        "semantic_correction_retries": correction_retries,
        "max_candidate_facts_per_source": fact_budget,
        "config_sha256": sha256_obj(config),
        "input_sha256": sha256_file(root / input_path),
        "provider": provider.stats(),
        "semantic_similarity": semantic_scorer.identity(),
        "result_sha256": sha256_file(output / "canary_results.jsonl"),
        "external_calls_performed": provider.physical_attempts,
        "retriever_calls_performed": 0,
        "victim_calls_performed": 0,
        "membership_read": False,
    }
    write_json(summary, output / "canary_summary.json")
    if passed != expected:
        raise RuntimeError(f"v24_canary_hard_gate_failed:{passed}/{expected}")
    return summary


def run_capacity_check(root: Path, *, dataset: str, sample_sources: int, use_luna: bool) -> dict[str, object]:
    if sample_sources <= 0:
        raise ValueError("v24_capacity_sample_invalid")
    config = load_v24_config(root)
    correction_retries = int(config.get("eligibility", {}).get("semantic_correction_retries", 1))
    fact_budget = get_max_candidate_facts_per_source(config)
    selected_sources: list[dict[str, object]] = []
    source_iter = iter_frozen_source_pool(root, dataset)
    for source in source_iter:
        selected_sources.append(source)
        if len(selected_sources) >= sample_sources:
            break
    semantic_scorer = build_v24_semantic_similarity(root) if use_luna else None
    provider = build_luna_candidate_provider(root) if use_luna else None
    eligible_count = 0
    screened_count = 0
    candidate_fact_count = 0
    processed_fact_count = 0
    unprocessed_fact_count = 0
    candidate_package_count = 0
    early_stop_source_count = 0
    diversity_counts = {"1": 0, "2": 0, "3": 0}
    if use_luna:
        try:
            for source in selected_sources:
                result = screen_source(
                    source,
                    candidate_provider=provider,
                    minimum_pairs=3,
                    allow_surface_fallback=False,
                    similarity_fn=semantic_scorer,
                    semantic_correction_retries=correction_retries,
                    max_candidate_facts_per_source=fact_budget,
                )
                screened_count += 1
                candidate_fact_count += int(result.get("candidate_fact_count", 0))
                processed_fact_count += int(result.get("processed_fact_count", 0))
                unprocessed_fact_count += int(result.get("unprocessed_fact_count", 0))
                candidate_package_count += int(result.get("candidate_package_count", 0))
                early_stop_source_count += int(bool(result.get("early_stop_triggered")))
                diversity = str(int(result.get("original_entity_diversity", 0)))
                if diversity in diversity_counts and result.get("eligible"):
                    diversity_counts[diversity] += 1
                eligible_count += int(bool(result.get("eligible")))
        finally:
            semantic_scorer.close()
    else:
        # Offline capacity sanity check: count source-grounded slots only.  It is
        # an estimate, never the exact eligibility scan and never a formal result.
        for source in selected_sources:
            screened_count += 1
            fact_count = len(enumerate_candidate_facts(source))
            # 此分支不调用 provider/Luna；预算内容量估计必须与实际处理计数分开。
            budgeted_fact_count = min(fact_count, fact_budget)
            candidate_fact_count += fact_count
            processed_fact_count += 0
            unprocessed_fact_count += fact_count
            eligible_count += int(budgeted_fact_count >= 3)
    rate = eligible_count / max(1, screened_count)
    target = int(config.get("eligibility", {}).get("target_sources", 2250))
    result = {
        "status": "passed",
        "dataset": dataset,
        "mode": "luna_sample" if use_luna else "offline_fact_capacity_estimate",
        "candidate_source_count": screened_count,
        "candidate_fact_count": candidate_fact_count,
        "processed_fact_count": processed_fact_count,
        "unprocessed_fact_count": unprocessed_fact_count,
        "candidate_package_count": candidate_package_count,
        "observed_eligible_source_rate": rate,
        "projected_eligible_source_count": int(round(rate * int(config.get("source_pool", {}).get("expected_source_counts", {}).get(dataset, 0) or 0))),
        "target_eligible_source_count": target,
        "max_candidate_facts_per_source": fact_budget,
        "early_stop_source_count": early_stop_source_count,
        "entity_diversity_1_source_count": diversity_counts["1"],
        "entity_diversity_2_source_count": diversity_counts["2"],
        "entity_diversity_3_source_count": diversity_counts["3"],
        "mean_original_entity_diversity": (
            sum(int(key) * value for key, value in diversity_counts.items())
            / max(1, eligible_count)
        ),
        "capacity_status": "estimate_only" if not use_luna else ("sufficient_sample_signal" if rate > 0 else "no_eligible_sample"),
        "provider": provider.stats() if provider is not None else None,
        "semantic_similarity": semantic_scorer.identity() if semantic_scorer is not None else None,
        "external_calls_performed": provider.physical_attempts if provider is not None else 0,
        "retriever_calls_performed": 0,
        "victim_calls_performed": 0,
        "membership_read": False,
    }
    write_json(result, root / CAPACITY_OUTPUT_DIR / f"{dataset}.json")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="v24 offline pre-split eligibility checks")
    parser.add_argument("command", choices=("validate-config", "source-pools", "validate-eligibility", "validate-split", "run-canary", "run-capacity-check"))
    parser.add_argument("--manifest", help="普通 v24 manifest 路径（仅 validate-* 命令使用）")
    parser.add_argument("--dataset", choices=("edgar", "enron", "pubmed"))
    parser.add_argument("--input", dest="input_path", help="membership-blind canary input JSONL")
    parser.add_argument("--output-dir", default=str(CANARY_OUTPUT_DIR))
    parser.add_argument("--sample-sources", type=int)
    parser.add_argument("--use-luna", action="store_true")
    args = parser.parse_args()
    if args.command == "validate-config":
        config = load_v24_config(PROJECT_ROOT)
        print(json.dumps({"status": "passed", "protocol_version": config["protocol_version"], "external_calls_performed": 0}, ensure_ascii=False))
    elif args.command == "source-pools":
        print(json.dumps({"status": "passed", "source_pools": source_pool_bindings(PROJECT_ROOT), "external_calls_performed": 0}, ensure_ascii=False))
    elif args.command in {"validate-eligibility", "validate-split"}:
        if not args.manifest:
            parser.error("validate-* requires --manifest")
        payload = read_json(Path(args.manifest))
        validator = validate_eligibility_manifest if args.command == "validate-eligibility" else validate_split_manifest
        result = validator(payload)
        print(json.dumps({**result, "external_calls_performed": 0}, ensure_ascii=False))
    elif args.command == "run-canary":
        input_path = args.input_path or load_v24_config(PROJECT_ROOT).get("development", {}).get("canary_input_path")
        if not input_path:
            parser.error("run-canary requires --input or development.canary_input_path")
        print(json.dumps(run_canary(PROJECT_ROOT, input_path=input_path, output_dir=args.output_dir), ensure_ascii=False))
    else:
        if not args.dataset:
            parser.error("run-capacity-check requires --dataset")
        config = load_v24_config(PROJECT_ROOT)
        sample_sources = args.sample_sources or int(config.get("development", {}).get("capacity_sample_sources", 30))
        print(json.dumps(run_capacity_check(PROJECT_ROOT, dataset=args.dataset, sample_sources=sample_sources, use_luna=args.use_luna), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
