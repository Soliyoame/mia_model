"""生成和评估 PCV stance parser 的人工审计样本。"""
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
from src.utils.run_context import model_scoped_dir, victim_model_slug  # noqa: E402


ANNOTATION_LABELS = (
    "supports_true_claim",
    "rejects_true_claim",
    "corrects_counterfactual",
    "rejects_counterfactual",
    "accepts_counterfactual",
    "unknown",
    "refuses",
    "unrelated",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sample or evaluate stance parser audit rows")
    parser.add_argument("--dataset", choices=["edgar", "enron", "both"], required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--annotations", default=None)
    parser.add_argument("--minimum-labeled", type=int, default=200)
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def stratified_sample(rows: list[dict[str, Any]], sample_size: int, seed: int) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[(str(row.get("dataset")), str(row.get("group")), str(row.get("claim_type")))].append(row)
    rng = random.Random(seed)
    for bucket in buckets.values():
        rng.shuffle(bucket)

    selected: list[dict[str, Any]] = []
    keys = sorted(buckets)
    while len(selected) < min(sample_size, len(rows)):
        progressed = False
        for key in keys:
            if buckets[key] and len(selected) < sample_size:
                selected.append(buckets[key].pop())
                progressed = True
        if not progressed:
            break
    return selected


def evaluate_annotations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [row for row in rows if str(row.get("human_stance") or "").strip()]
    invalid = sorted({
        str(row.get("human_stance")) for row in labeled
        if str(row.get("human_stance")) not in ANNOTATION_LABELS
    })
    if invalid:
        raise ValueError(f"Invalid human_stance labels: {invalid}")
    labels = sorted({str(row.get("stance")) for row in labeled} | {str(row.get("human_stance")) for row in labeled})
    confusion = {truth: {pred: 0 for pred in labels} for truth in labels}
    for row in labeled:
        confusion[str(row["human_stance"])][str(row["stance"])] += 1

    per_class: dict[str, Any] = {}
    for label in labels:
        tp = confusion[label][label]
        fp = sum(confusion[truth][label] for truth in labels if truth != label)
        fn = sum(confusion[label][pred] for pred in labels if pred != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}
    correct = sum(confusion[label][label] for label in labels)
    return {
        "labeled_rows": len(labeled),
        "accuracy": correct / len(labeled) if labeled else None,
        "macro_f1": sum(row["f1"] for row in per_class.values()) / len(per_class) if per_class else None,
        "labels": labels,
        "per_class": per_class,
        "confusion_matrix": confusion,
        "strata": dict(Counter(
            f"{row.get('dataset')}::{row.get('group')}::{row.get('claim_type')}"
            for row in labeled
        )),
    }


def _load_joined_rows(dataset: str, model: str) -> list[dict[str, Any]]:
    parsed_path = model_scoped_dir("outputs/parsed_stance", dataset, model=model) / f"{dataset}_parsed_stance.jsonl"
    response_path = model_scoped_dir("outputs/rag_responses", dataset, model=model) / f"{dataset}_rag_responses.jsonl"
    if not parsed_path.exists() or not response_path.exists():
        raise FileNotFoundError(f"Required parsed/response artifacts are missing for {dataset}/{model}")
    responses = {str(row.get("query_id")): row for row in read_jsonl(response_path) if row.get("query_id")}
    joined: list[dict[str, Any]] = []
    for row in read_jsonl(parsed_path):
        if str(row.get("mode")) != "rag":
            continue
        response = responses.get(str(row.get("query_id")), {})
        joined.append({
            "dataset": dataset,
            "model": model,
            "query_id": row.get("query_id"),
            "audit_id": row.get("audit_id"),
            "source_key": row.get("source_key"),
            "group": row.get("group"),
            "claim_type": row.get("claim_type"),
            "expected_entity": row.get("expected_entity"),
            "counterfactual_entity": row.get("counterfactual_entity"),
            "query": response.get("query", ""),
            "response": response.get("response", ""),
            "stance": row.get("stance"),
            "human_stance": "",
            "audit_notes": "",
        })
    return joined


def _datasets(value: str) -> tuple[str, ...]:
    return ("edgar", "enron") if value == "both" else (value,)


def _output_base(dataset: str, model: str) -> Path:
    if dataset == "both":
        return ensure_dir(resolve_path("outputs/diagnostics/stance_audit") / model)
    return model_scoped_dir("outputs/diagnostics", dataset, model=model)


def main() -> int:
    args = parse_args()
    model = args.model or victim_model_slug()
    base = _output_base(args.dataset, model)
    if args.annotations:
        annotation_path = Path(args.annotations)
        result = evaluate_annotations(list(read_jsonl(annotation_path)))
        result.update({
            "dataset": args.dataset,
            "model": model,
            "annotation_path": str(annotation_path.resolve()),
            "annotation_hash": sha256_file(annotation_path),
            "minimum_labeled": args.minimum_labeled,
            "minimum_labeled_met": result["labeled_rows"] >= args.minimum_labeled,
        })
        output = Path(args.output) if args.output else base / f"{args.dataset}_stance_audit_report.json"
        ensure_dir(output.parent)
        write_json(result, output)
        print(f"[saved] {output}")
        return 0

    candidates: list[dict[str, Any]] = []
    for dataset in _datasets(args.dataset):
        candidates.extend(_load_joined_rows(dataset, model))
    rows = stratified_sample(candidates, args.sample_size, args.seed)
    output = Path(args.output) if args.output else base / f"{args.dataset}_stance_audit_annotations.jsonl"
    ensure_dir(output.parent)
    write_jsonl(rows, output)
    manifest = {
        "dataset": args.dataset,
        "datasets": list(_datasets(args.dataset)),
        "model": model,
        "seed": args.seed,
        "requested_sample_size": args.sample_size,
        "sampled_rows": len(rows),
        "source_count": len({str(row.get("source_key")) for row in rows}),
        "strata": dict(Counter(
            f"{row.get('dataset')}::{row.get('group')}::{row.get('claim_type')}"
            for row in rows
        )),
        "sample_whitelist_hash": sha256_obj(sorted(str(row.get("query_id")) for row in rows)),
        "annotation_labels": list(ANNOTATION_LABELS),
        "instructions": "Read query and response; fill human_stance with exactly one annotation_labels value. Do not edit parser stance.",
        "output_path": str(output.resolve()),
        "output_hash": sha256_file(output),
    }
    write_json(manifest, output.with_suffix(".manifest.json"))
    print(f"[saved] {output} ({len(rows)} rows; fill human_stance then rerun with --annotations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
