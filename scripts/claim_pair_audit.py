"""Create and evaluate double-blind human audits for validated claim pairs."""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import ensure_dir, read_jsonl, resolve_path, write_json, write_jsonl  # noqa: E402


HUMAN_LABELS = ("pass", "fail")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build or evaluate double-blind claim-pair audits")
    parser.add_argument("--dataset", choices=["edgar", "enron", "pubmed"], required=True)
    parser.add_argument("--claims", default=None)
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--annotations-a", default=None)
    parser.add_argument("--annotations-b", default=None)
    parser.add_argument("--minimum-pass-rate", type=float, default=0.90)
    parser.add_argument("--minimum-kappa", type=float, default=0.80)
    parser.add_argument("--output-dir", default="outputs/diagnostics/claim_pair_audit")
    parser.add_argument(
        "--exclude-audit-dir",
        action="append",
        default=[],
        help=(
            "Prior audit directory to exclude by source_key and audit_id. "
            "Repeat the option to exclude multiple independent audit rounds."
        ),
    )
    return parser.parse_args()


def _source_key(row: dict[str, Any]) -> str:
    return str(row.get("source_key") or row.get("source_id") or row.get("doc_id") or "")


def stratified_source_sample(
    rows: list[dict[str, Any]], sample_size: int, seed: int
) -> list[dict[str, Any]]:
    """Balance group/entity strata and prefer one pair per source."""

    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[(str(row.get("group")), str(row.get("entity_type")))].append(row)
    rng = random.Random(seed)
    for bucket in buckets.values():
        rng.shuffle(bucket)

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    seen_sources: set[str] = set()
    keys = sorted(buckets)
    while len(selected) < min(sample_size, len(rows)):
        progressed = False
        for key in keys:
            for candidate in buckets[key]:
                identity = id(candidate)
                source = _source_key(candidate)
                if identity in selected_ids or (source and source in seen_sources):
                    continue
                selected.append(candidate)
                selected_ids.add(identity)
                if source:
                    seen_sources.add(source)
                progressed = True
                break
            if len(selected) >= sample_size:
                break
        if not progressed:
            break
    if len(selected) < min(sample_size, len(rows)):
        remaining = [row for row in rows if id(row) not in selected_ids]
        rng.shuffle(remaining)
        selected.extend(remaining[: sample_size - len(selected)])
    return selected


def load_audit_exclusions(
    audit_dir: Path,
    dataset: str,
) -> dict[str, Any]:
    """Load a prior A/B audit as a source- and pair-level exclusion set."""

    path_a = audit_dir / f"{dataset}_claim_pair_audit_annotator_a.jsonl"
    path_b = audit_dir / f"{dataset}_claim_pair_audit_annotator_b.jsonl"
    for path in (path_a, path_b):
        if not path.exists():
            raise FileNotFoundError(path)
    rows_a = list(read_jsonl(path_a))
    rows_b = list(read_jsonl(path_b))
    ids_a = {str(row.get("audit_id") or "") for row in rows_a}
    ids_b = {str(row.get("audit_id") or "") for row in rows_b}
    if "" in ids_a or "" in ids_b or ids_a != ids_b:
        raise ValueError(f"{dataset}: prior A/B audit ID sets do not match")
    sources = {
        _source_key(row)
        for row in [*rows_a, *rows_b]
        if _source_key(row)
    }
    return {
        "source_keys": sources,
        "audit_ids": ids_a,
        "path_a": path_a,
        "path_b": path_b,
        "path_a_hash": sha256_file(path_a),
        "path_b_hash": sha256_file(path_b),
    }


def filter_audit_exclusions(
    rows: list[dict[str, Any]],
    *,
    source_keys: set[str],
    audit_ids: set[str],
) -> list[dict[str, Any]]:
    """Remove rows sharing a prior audit source or pair/audit identity."""

    return [
        row
        for row in rows
        if _source_key(row) not in source_keys
        and str(row.get("pair_id") or row.get("claim_pair_id") or row.get("audit_id") or "")
        not in audit_ids
    ]


def blind_claim_rows(
    rows: list[dict[str, Any]],
    annotator_role: str,
    *,
    shuffle_seed: int | None = None,
) -> list[dict[str, Any]]:
    ordered_rows = list(rows)
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(ordered_rows)
    output: list[dict[str, Any]] = []
    for index, row in enumerate(ordered_rows):
        audit_id = str(row.get("pair_id") or row.get("claim_pair_id") or "")
        if not audit_id:
            audit_id = sha256_obj(
                [row.get("dataset"), _source_key(row), row.get("true_claim"), row.get("counterfactual_claim")]
            )[:20]
        output.append({
            "audit_id": audit_id,
            "audit_order": index + 1,
            "annotator_role": annotator_role,
            "dataset": row.get("dataset"),
            "source_key": _source_key(row),
            "entity_type": row.get("entity_type"),
            "original_entity": row.get("original_entity"),
            "counterfactual_entity": row.get("counterfactual_entity"),
            "true_claim": row.get("true_claim"),
            "counterfactual_claim": row.get("counterfactual_claim"),
            "human_pair_valid": "",
            "human_failure_reason": "",
            "audit_notes": "",
        })
    return output


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float | None:
    if not labels_a or len(labels_a) != len(labels_b):
        return None
    total = len(labels_a)
    observed = sum(left == right for left, right in zip(labels_a, labels_b)) / total
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    expected = sum((counts_a[label] / total) * (counts_b[label] / total) for label in HUMAN_LABELS)
    if expected == 1.0:
        # 两位标注者都只使用同一类别时，κ 的分母为零；不能把未定义伪装成完美一致。
        return None
    return (observed - expected) / (1.0 - expected)


def evaluate_double_annotations(
    rows_a: list[dict[str, Any]],
    rows_b: list[dict[str, Any]],
    *,
    minimum_labeled: int = 200,
    minimum_pass_rate: float = 0.90,
    minimum_kappa: float = 0.80,
) -> dict[str, Any]:
    by_a = {str(row.get("audit_id")): row for row in rows_a}
    by_b = {str(row.get("audit_id")): row for row in rows_b}
    if len(by_a) != len(rows_a) or len(by_b) != len(rows_b):
        raise ValueError("Duplicate audit_id in claim-pair annotations")
    if set(by_a) != set(by_b):
        raise ValueError("Annotator A/B claim-pair samples do not match")

    labels_a: list[str] = []
    labels_b: list[str] = []
    for audit_id in sorted(by_a):
        left = str(by_a[audit_id].get("human_pair_valid") or "").strip().lower()
        right = str(by_b[audit_id].get("human_pair_valid") or "").strip().lower()
        if not left or not right:
            continue
        if left not in HUMAN_LABELS or right not in HUMAN_LABELS:
            raise ValueError(f"Invalid human_pair_valid label for {audit_id}: {left!r}/{right!r}")
        labels_a.append(left)
        labels_b.append(right)

    kappa = cohen_kappa(labels_a, labels_b)
    double_pass_rate = (
        sum(left == "pass" and right == "pass" for left, right in zip(labels_a, labels_b)) / len(labels_a)
        if labels_a else None
    )
    gate = bool(
        len(labels_a) >= minimum_labeled
        and double_pass_rate is not None
        and double_pass_rate >= minimum_pass_rate
        and kappa is not None
        and kappa >= minimum_kappa
    )
    return {
        "matched_rows": len(by_a),
        "double_labeled_rows": len(labels_a),
        "agreement_rate": (
            sum(left == right for left, right in zip(labels_a, labels_b)) / len(labels_a)
            if labels_a else None
        ),
        "cohen_kappa": kappa,
        "double_pass_rate": double_pass_rate,
        "minimum_labeled": minimum_labeled,
        "minimum_pass_rate": minimum_pass_rate,
        "minimum_kappa": minimum_kappa,
        "quality_gate_passed": gate,
    }


def main() -> int:
    args = parse_args()
    output_dir = ensure_dir(resolve_path(args.output_dir))
    if args.annotations_a or args.annotations_b:
        if not args.annotations_a or not args.annotations_b:
            raise ValueError("Both --annotations-a and --annotations-b are required")
        path_a = Path(args.annotations_a)
        path_b = Path(args.annotations_b)
        report = evaluate_double_annotations(
            list(read_jsonl(path_a)),
            list(read_jsonl(path_b)),
            minimum_labeled=args.sample_size,
            minimum_pass_rate=args.minimum_pass_rate,
            minimum_kappa=args.minimum_kappa,
        )
        report.update({
            "dataset": args.dataset,
            "annotations_a": str(path_a.resolve()),
            "annotations_b": str(path_b.resolve()),
            "annotations_a_hash": sha256_file(path_a),
            "annotations_b_hash": sha256_file(path_b),
        })
        output = output_dir / f"{args.dataset}_claim_pair_audit_report.json"
        write_json(report, output)
        print(f"[saved] {output}")
        return 0

    claims_path = Path(args.claims) if args.claims else resolve_path("outputs/paired_claims") / f"{args.dataset}_paired_claims.jsonl"
    rows = list(read_jsonl(claims_path))
    rows_before_exclusion = len(rows)
    exclusion_manifests: list[dict[str, Any]] = []
    excluded_source_keys: set[str] = set()
    excluded_audit_ids: set[str] = set()
    for audit_dir_arg in args.exclude_audit_dir:
        exclusion_dir = resolve_path(audit_dir_arg)
        exclusions = load_audit_exclusions(exclusion_dir, args.dataset)
        excluded_source_keys.update(exclusions["source_keys"])
        excluded_audit_ids.update(exclusions["audit_ids"])
        exclusion_manifests.append({
            "audit_dir": str(exclusion_dir.resolve()),
            "annotator_a_path": str(exclusions["path_a"].resolve()),
            "annotator_b_path": str(exclusions["path_b"].resolve()),
            "annotator_a_hash": exclusions["path_a_hash"],
            "annotator_b_hash": exclusions["path_b_hash"],
            "excluded_source_count": len(exclusions["source_keys"]),
            "excluded_audit_id_count": len(exclusions["audit_ids"]),
        })
    if exclusion_manifests:
        rows = filter_audit_exclusions(
            rows,
            source_keys=excluded_source_keys,
            audit_ids=excluded_audit_ids,
        )
    sampled = stratified_source_sample(rows, args.sample_size, args.seed)
    if len(sampled) != args.sample_size:
        raise RuntimeError(f"Need {args.sample_size} claim pairs for {args.dataset}, found {len(sampled)}")
    path_a = output_dir / f"{args.dataset}_claim_pair_audit_annotator_a.jsonl"
    path_b = output_dir / f"{args.dataset}_claim_pair_audit_annotator_b.jsonl"
    annotator_a_seed = args.seed + 1001
    annotator_b_seed = args.seed + 2002
    rows_a = blind_claim_rows(sampled, "A", shuffle_seed=annotator_a_seed)
    rows_b = blind_claim_rows(sampled, "B", shuffle_seed=annotator_b_seed)
    write_jsonl(rows_a, path_a)
    write_jsonl(rows_b, path_b)
    manifest = {
        "dataset": args.dataset,
        "seed": args.seed,
        "sample_size": args.sample_size,
        "source_count": len({_source_key(row) for row in sampled}),
        "strata": dict(Counter(f"{row.get('group')}::{row.get('entity_type')}" for row in sampled)),
        "sample_whitelist_hash": sha256_obj(sorted(row["audit_id"] for row in rows_a)),
        "annotator_a_shuffle_seed": annotator_a_seed,
        "annotator_b_shuffle_seed": annotator_b_seed,
        "claims_path": str(claims_path.resolve()),
        "claims_hash": sha256_file(claims_path),
        "prior_audit_exclusions": exclusion_manifests,
        "prior_audit_exclusion_summary": {
            "audit_directory_count": len(exclusion_manifests),
            "excluded_source_count": len(excluded_source_keys),
            "excluded_audit_id_count": len(excluded_audit_ids),
            "candidate_rows_before": rows_before_exclusion,
            "candidate_rows_after": len(rows),
            "candidate_rows_removed": rows_before_exclusion - len(rows),
        },
        "annotation_labels": list(HUMAN_LABELS),
        "instructions": (
            "Annotate independently. Mark pass only if entity boundaries, one-slot substitution, type, "
            "counterfactual difference, and claim completeness are all correct. Do not consult the other annotator."
        ),
        "annotator_a_path": str(path_a.resolve()),
        "annotator_b_path": str(path_b.resolve()),
        "annotator_a_hash": sha256_file(path_a),
        "annotator_b_hash": sha256_file(path_b),
    }
    write_json(manifest, output_dir / f"{args.dataset}_claim_pair_audit_manifest.json")
    print(f"[saved] {path_a} and {path_b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
