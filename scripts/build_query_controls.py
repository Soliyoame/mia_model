"""构建需要重新查询的 PCV-MIA query controls，不改变 01-15 主流水线。"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.paired_claims.claim_generator import _find_entity_span  # noqa: E402
from src.query_generation.paired_query_builder import build_verification_query  # noqa: E402
from src.query_generation.stealth_filter import filter_stealth_queries  # noqa: E402
from src.rag.embeddings import DEFAULT_EMBEDDING_MODEL  # noqa: E402
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import ensure_dir, load_yaml, read_jsonl, resolve_path, write_json, write_jsonl  # noqa: E402


QUERY_CONTROL_VARIANTS = (
    "random_same_type_counterfactual",
    "independent_unpaired_query",
    "no_stealth_filter",
)


def _safe_variant(value: str) -> str:
    variant = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if variant not in QUERY_CONTROL_VARIANTS:
        raise ValueError(f"Unsupported query control: {value}")
    return variant


def build_random_same_type_pairs(
    pairs: list[dict[str, Any]],
    *,
    seed: int = 42,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """从其它 source 的同类型真实实体池随机抽取反事实，保持其余声明不变。"""
    pools: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for pair in pairs:
        pools[str(pair.get("entity_type"))].append((
            str(pair.get("original_entity") or ""),
            str(pair.get("source_key") or pair.get("source_id") or ""),
        ))
    rng = random.Random(seed)
    output: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for pair in sorted(pairs, key=lambda row: str(row.get("pair_id") or "")):
        original = str(pair.get("original_entity") or "")
        source_key = str(pair.get("source_key") or pair.get("source_id") or "")
        candidates = sorted({
            value for value, candidate_source in pools[str(pair.get("entity_type"))]
            if value and value != original and candidate_source != source_key
        })
        span = _find_entity_span(str(pair.get("true_claim") or ""), original)
        if not candidates or span is None:
            errors.append({"pair_id": pair.get("pair_id"), "error": "no_cross_source_same_type_candidate"})
            continue
        counterfactual = rng.choice(candidates)
        true_claim = str(pair["true_claim"])
        output.append({
            **pair,
            "counterfactual_entity": counterfactual,
            "counterfactual_claim": true_claim[:span[0]] + counterfactual + true_claim[span[1]:],
            "control_variant": "random_same_type_counterfactual",
        })
    return output, errors


def _query_row(
    pair: dict[str, Any],
    *,
    variant_id: str,
    claim_type: str,
    query: str,
    query_type: str,
) -> dict[str, Any]:
    is_true = claim_type == "true"
    return {
        "query_id": f"q_{variant_id}_{pair['pair_id']}_{'plus' if is_true else 'minus'}",
        "pair_id": pair["pair_id"],
        "fact_id": pair["fact_id"],
        "audit_id": pair["audit_id"],
        "doc_id": pair.get("doc_id"),
        "source_id": pair.get("source_id") or pair.get("doc_id"),
        "source_key": pair.get("source_key") or pair.get("source_id") or pair.get("doc_id"),
        "dataset": pair["dataset"],
        "group": pair["group"],
        "variant_id": variant_id,
        "claim_type": claim_type,
        "query_type": query_type,
        "query": query,
        "claim": pair["true_claim"] if is_true else pair["counterfactual_claim"],
        "true_claim": pair["true_claim"],
        "counterfactual_claim": pair["counterfactual_claim"],
        "expected_entity": pair["original_entity"],
        "original_entity": pair["original_entity"],
        "counterfactual_entity": None if is_true else pair["counterfactual_entity"],
        "entity_type": pair["entity_type"],
        "perturbation_level": pair.get("perturbation_level"),
        "source_text": pair["true_claim"],
    }


def build_control_query_rows(
    pairs: list[dict[str, Any]],
    variant_id: str,
    *,
    seed: int = 42,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """构建固定 query plan；所有随机性只由 seed 决定。"""
    variant = _safe_variant(variant_id)
    selected_pairs = pairs
    errors: list[dict[str, Any]] = []
    if variant == "random_same_type_counterfactual":
        selected_pairs, errors = build_random_same_type_pairs(pairs, seed=seed)

    rows: list[dict[str, Any]] = []
    for pair in sorted(selected_pairs, key=lambda row: str(row.get("pair_id") or "")):
        if variant == "independent_unpaired_query":
            plus_type = "direct_verification"
            minus_type = "role_based_audit"
            logical_type = "independent_unpaired_query"
        else:
            plus_type = minus_type = "compressed_verification"
            logical_type = "compressed_verification"
        for claim_type, style in (("true", plus_type), ("counterfactual", minus_type)):
            rows.append(_query_row(
                pair,
                variant_id=variant,
                claim_type=claim_type,
                query=build_verification_query(pair, claim_type, style),
                query_type=logical_type,
            ))
    return rows, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build PCV-MIA online query controls")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--variant", choices=QUERY_CONTROL_VARIANTS, required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    config = load_yaml(config_path)
    variant = _safe_variant(args.variant)
    root = ensure_dir(resolve_path("outputs/query_controls") / args.dataset / variant)
    planned_path = root / "planned_queries.jsonl"
    accepted_path = root / "queries.jsonl"
    rejected_path = root / "rejected_queries.jsonl"
    control_manifest_path = root / "control_manifest.json"
    if control_manifest_path.exists() and accepted_path.exists() and not args.force:
        print(f"[skip] {control_manifest_path}")
        return 0

    claims_path = resolve_path(config["paths"]["paired_claims_dir"]) / f"{args.dataset}_paired_claims.jsonl"
    pairs = list(read_jsonl(claims_path))
    planned, errors = build_control_query_rows(pairs, variant, seed=args.seed)
    write_jsonl(planned, planned_path)

    filter_manifest: dict[str, Any]
    if variant == "no_stealth_filter":
        accepted = [{**row, "accepted": True, "reject_reason": None} for row in planned]
        write_jsonl(accepted, accepted_path)
        write_jsonl([], rejected_path)
        filter_manifest = {
            "filter_applied": False,
            "accepted": len(accepted),
            "rejected": 0,
            "accepted_pairs": len(accepted) // 2,
        }
    else:
        stealth = config.get("stealth_filter", {})
        filter_manifest = filter_stealth_queries(
            planned_path,
            accepted_path,
            rejected_path=rejected_path,
            embedding_model=str(stealth.get("embedding_model", DEFAULT_EMBEDDING_MODEL)),
            min_naturalness=float(stealth.get("min_naturalness", 0.55)),
            max_context_probe=float(stealth.get("max_context_probe", 0.5)),
            max_prompt_injection=float(stealth.get("max_prompt_injection", 0.5)),
            min_similarity=float(stealth.get("min_similarity", 0.03)),
            max_similarity=float(stealth.get("max_similarity", 0.97)),
            resume=False,
            force=True,
        )
        accepted = list(read_jsonl(accepted_path))

    source_keys = sorted({
        str(row.get("source_key")) for row in accepted
        if str(row.get("group")) in {"KB_Member", "True_Non_Member"}
    })
    manifest = {
        "dataset": args.dataset,
        "variant_id": variant,
        "seed": args.seed,
        "query_budget_definition": "two victim calls per retained logical pair",
        "planned_queries": len(planned),
        "accepted_queries": len(accepted),
        "construction_errors": len(errors),
        "errors": errors,
        "source_count": len(source_keys),
        "source_whitelist_hash": sha256_obj(source_keys),
        "benchmark_hash": (
            resolve_path("datasets/benchmarks") / f"{args.dataset}_attack_benchmark.sha256"
        ).read_text(encoding="utf-8").strip(),
        "config_hash": sha256_file(config_path),
        "paired_claims_hash": sha256_file(claims_path),
        "planned_queries_hash": sha256_file(planned_path),
        "accepted_queries_hash": sha256_file(accepted_path),
        "filter": filter_manifest,
    }
    write_json(manifest, control_manifest_path)
    print(f"[saved] {control_manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
