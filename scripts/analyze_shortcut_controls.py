"""Evaluate non-PCV shortcut signals on the same source-level whitelist as full PVS."""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.metrics import (  # noqa: E402
    bootstrap_auc_ci,
    paired_bootstrap_metric_delta,
    summarize_membership_scores,
)
from src.rag.embeddings import build_embedding_model, cosine_similarity  # noqa: E402
from src.rag.runner import response_is_success  # noqa: E402
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import ensure_dir, load_yaml, read_jsonl, resolve_path, write_json, write_jsonl  # noqa: E402
from src.utils.run_context import git_snapshot, model_scoped_dir, victim_model_slug  # noqa: E402

EVAL_GROUPS = {"KB_Member", "True_Non_Member"}
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
FEATURE_ACCESS = {
    "lexical_query_document_jaccard": "researcher_only_target_document",
    "embedding_query_document_cosine": "researcher_only_target_document",
    "retrieval_target_hit_rate": "researcher_only_internal_retrieval",
    "retrieval_max_score": "researcher_only_internal_retrieval",
    "query_token_count": "attack_query_only",
    "query_char_count": "attack_query_only",
    "query_digit_ratio": "attack_query_only",
    "query_punctuation_ratio": "attack_query_only",
}


def lexical_jaccard(left: str, right: str) -> float:
    left_tokens = set(TOKEN_RE.findall(left.lower()))
    right_tokens = set(TOKEN_RE.findall(right.lower()))
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_source_shortcut_features(
    query_rows: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]],
    rag_rows: list[dict[str, Any]],
    embedding_model: Any,
) -> list[dict[str, Any]]:
    """Compute query-level features, then equal-mean query→chunk→source."""
    benchmark = {str(row.get("audit_id")): row for row in benchmark_rows}
    responses = {
        str(row.get("query_id")): row
        for row in rag_rows
        if response_is_success(row)
    }
    selected = [
        row for row in query_rows
        if row.get("accepted", True)
        and str(row.get("group")) in EVAL_GROUPS
        and str(row.get("audit_id")) in benchmark
    ]
    query_texts = [str(row.get("query") or "") for row in selected]
    document_texts = [str(benchmark[str(row.get("audit_id"))].get("text") or "") for row in selected]
    query_vectors = embedding_model.encode(query_texts)
    document_vectors = embedding_model.encode(document_texts)

    by_source_audit: dict[tuple[str, str], list[dict[str, float]]] = defaultdict(list)
    source_meta: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(selected):
        query = query_texts[index]
        document = document_texts[index]
        source_key = str(row.get("source_key") or row.get("source_id") or row.get("doc_id"))
        audit_id = str(row.get("audit_id"))
        response = responses.get(str(row.get("query_id")))
        retrieval_scores = response.get("retrieval_scores", []) if response else []
        chars = len(query)
        features: dict[str, float] = {
            "lexical_query_document_jaccard": lexical_jaccard(query, document),
            "embedding_query_document_cosine": cosine_similarity(
                query_vectors[index], document_vectors[index]
            ),
            "query_token_count": float(len(TOKEN_RE.findall(query))),
            "query_char_count": float(chars),
            "query_digit_ratio": (
                sum(character.isdigit() for character in query) / chars if chars else 0.0
            ),
            "query_punctuation_ratio": (
                sum(not character.isalnum() and not character.isspace() for character in query) / chars
                if chars else 0.0
            ),
        }
        if response is not None:
            features["retrieval_target_hit_rate"] = float(bool(response.get("target_doc_retrieved")))
            features["retrieval_max_score"] = max((float(value) for value in retrieval_scores), default=0.0)
        by_source_audit[(source_key, audit_id)].append(features)
        meta = source_meta.setdefault(source_key, {
            "source_key": source_key,
            "source_id": row.get("source_id") or source_key,
            "group": row.get("group"),
            "query_count": 0,
            "audit_ids": set(),
        })
        if str(meta.get("group")) != str(row.get("group")):
            raise RuntimeError(f"Source crosses labels: {source_key}")
        meta["query_count"] += 1
        meta["audit_ids"].add(audit_id)

    chunk_features: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for (source_key, _), rows in by_source_audit.items():
        for feature in FEATURE_ACCESS:
            values = [float(row[feature]) for row in rows if feature in row and math.isfinite(float(row[feature]))]
            if values:
                chunk_features[source_key][feature].append(_mean(values))

    output: list[dict[str, Any]] = []
    for source_key, meta in sorted(source_meta.items()):
        row: dict[str, Any] = {
            **meta,
            "audit_ids": sorted(meta["audit_ids"]),
            "chunk_count": len(meta["audit_ids"]),
        }
        for feature, values in chunk_features[source_key].items():
            row[feature] = _mean(values)
        output.append(row)
    return output


def build_shortcut_report(
    main_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    *,
    n_bootstrap: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    main = {
        str(row.get("source_key")): row
        for row in main_rows
        if str(row.get("group")) in EVAL_GROUPS
    }
    report: dict[str, Any] = {}
    for feature, access_class in FEATURE_ACCESS.items():
        available = {
            str(row.get("source_key")): row
            for row in feature_rows
            if str(row.get("group")) in EVAL_GROUPS
            and row.get(feature) is not None
            and math.isfinite(float(row[feature]))
        }
        common = sorted(
            key for key in set(main) & set(available)
            if str(main[key].get("group")) == str(available[key].get("group"))
        )
        left = [main[key] for key in common]
        right = [available[key] for key in common]
        metrics = summarize_membership_scores(right, score_key=feature)
        auc = metrics.get("AUC")
        report[feature] = {
            "variant_id": f"shortcut:{feature}",
            "access_class": access_class,
            "strict_black_box_attack_feature": access_class == "attack_query_only",
            "source_count": len(common),
            "source_whitelist_hash": sha256_obj(common),
            "metrics": metrics,
            "auc_ci95": bootstrap_auc_ci(
                right, score_key=feature, n_bootstrap=n_bootstrap, seed=seed
            ),
            "two_sided_separability_auc": (
                max(float(auc), 1.0 - float(auc)) if auc is not None else None
            ),
            "paired_delta_full_pvs_minus_shortcut": paired_bootstrap_metric_delta(
                left,
                right,
                left_score_key="pcv_score",
                right_score_key=feature,
                n_bootstrap=n_bootstrap,
                seed=seed,
            ),
        }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze PCV-MIA shortcut controls")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--attack-config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument("--rag-config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--allow-model-download",
        action="store_true",
        help="允许 embedding 加载器联网；默认只使用本地缓存以保证正式复现不受网络状态影响",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = args.model or victim_model_slug()
    attack_config_path = Path(args.attack_config)
    rag_config_path = Path(args.rag_config)
    attack_config = load_yaml(attack_config_path)
    rag_config = load_yaml(rag_config_path)
    queries_path = (
        resolve_path(attack_config["paths"]["stealth_filtered_queries_dir"])
        / f"{args.dataset}_paired_queries.jsonl"
    )
    benchmark_path = (
        resolve_path(attack_config["paths"]["benchmark_dir"])
        / f"{args.dataset}_attack_benchmark.jsonl"
    )
    rag_path = (
        model_scoped_dir("outputs/rag_responses", args.dataset, model=model)
        / f"{args.dataset}_rag_responses.jsonl"
    )
    main_source_path = (
        model_scoped_dir("outputs/scores", args.dataset, model=model)
        / f"{args.dataset}_pcv_scores_source_scores.jsonl"
    )
    missing = [str(path) for path in (queries_path, benchmark_path, rag_path, main_source_path) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Shortcut-control inputs are incomplete: {missing}")

    embedding = rag_config.get("embedding", {})
    embedding_model = build_embedding_model(
        embedding.get("model"),
        backend=str(embedding.get("backend", "auto")),
        dim=int(embedding.get("dim", 384)),
        local_files_only=not args.allow_model_download,
    )
    feature_rows = build_source_shortcut_features(
        list(read_jsonl(queries_path)),
        list(read_jsonl(benchmark_path)),
        list(read_jsonl(rag_path)),
        embedding_model,
    )
    diagnostics_dir = ensure_dir(model_scoped_dir("outputs/diagnostics", args.dataset, model=model))
    feature_path = diagnostics_dir / f"{args.dataset}_shortcut_source_features.jsonl"
    write_jsonl(feature_rows, feature_path)
    report = {
        "dataset": args.dataset,
        "model": model,
        "evaluation_unit": "source",
        "seed": args.seed,
        "bootstrap": args.bootstrap,
        "warning": (
            "Target-document and retrieval-internal features are researcher-only controls; "
            "they are not available to the strict black-box attacker."
        ),
        "embedding_model": getattr(embedding_model, "name", str(embedding.get("model"))),
        "benchmark_hash": (
            benchmark_path.with_suffix(".sha256").read_text(encoding="utf-8").strip()
            if benchmark_path.with_suffix(".sha256").exists() else sha256_file(benchmark_path)
        ),
        "attack_config_hash": sha256_file(attack_config_path),
        "rag_config_hash": sha256_file(rag_config_path),
        "code": git_snapshot(),
        "input_provenance": {
            "queries": {"path": str(queries_path), "sha256": sha256_file(queries_path)},
            "benchmark": {"path": str(benchmark_path), "sha256": sha256_file(benchmark_path)},
            "rag_responses": {"path": str(rag_path), "sha256": sha256_file(rag_path)},
            "main_source_scores": {"path": str(main_source_path), "sha256": sha256_file(main_source_path)},
        },
        "features_path": str(feature_path),
        "features_hash": sha256_file(feature_path),
        "features": build_shortcut_report(
            list(read_jsonl(main_source_path)),
            feature_rows,
            n_bootstrap=args.bootstrap,
            seed=args.seed,
        ),
    }
    output = Path(args.output) if args.output else diagnostics_dir / f"{args.dataset}_shortcut_controls.json"
    write_json(report, output)
    print(f"[saved] {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
