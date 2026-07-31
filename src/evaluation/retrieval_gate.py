"""Reserve-only pseudo-member 检索门禁与无攻击指标裁决。"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from typing import Any, Iterable, Protocol


class RetrieverLike(Protocol):
    def retrieve(self, query: str, top_k: int = 5) -> list[Any]:
        ...


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return float(ordered[position])


def evaluate_target_retrieval(
    retriever: RetrieverLike,
    queries: Iterable[dict[str, Any]],
    benchmark_by_audit: dict[str, dict[str, Any]],
    *,
    retrieve_top_k: int = 10,
) -> dict[str, Any]:
    """计算 target-doc Recall@k、MRR、source 零命中率和 p95 延迟。"""

    eligible = [
        row
        for row in queries
        if str(row.get("group") or "") == "Reserve"
        and str(row.get("audit_id") or "") in benchmark_by_audit
    ]
    hits_at_5 = 0
    hits_at_10 = 0
    reciprocal_ranks: list[float] = []
    latencies_ms: list[float] = []
    source_hits: dict[str, bool] = defaultdict(bool)
    for row in eligible:
        sample = benchmark_by_audit[str(row["audit_id"])]
        target_doc_id = str(sample.get("doc_id") or row.get("doc_id") or "")
        source_key = str(
            row.get("source_key")
            or row.get("source_id")
            or sample.get("source_key")
            or sample.get("source_id")
            or row["audit_id"]
        )
        started = time.perf_counter()
        retrieved = retriever.retrieve(str(row.get("query") or ""), top_k=retrieve_top_k)
        latencies_ms.append((time.perf_counter() - started) * 1000.0)
        doc_ids = [str(item.doc_id) for item in retrieved]
        try:
            rank = doc_ids.index(target_doc_id) + 1
        except ValueError:
            rank = 0
        hits_at_5 += int(0 < rank <= 5)
        hits_at_10 += int(0 < rank <= 10)
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        source_hits[source_key] = source_hits[source_key] or bool(rank)
    query_count = len(eligible)
    source_count = len(source_hits)
    zero_hit_sources = sum(1 for hit in source_hits.values() if not hit)
    return {
        "query_count": query_count,
        "source_count": source_count,
        "target_doc_recall_at_5": hits_at_5 / query_count if query_count else 0.0,
        "target_doc_recall_at_10": hits_at_10 / query_count if query_count else 0.0,
        "mrr": sum(reciprocal_ranks) / query_count if query_count else 0.0,
        "zero_hit_sources": zero_hit_sources,
        "zero_hit_source_rate": zero_hit_sources / source_count if source_count else 1.0,
        "latency_ms_p95": percentile(latencies_ms, 0.95),
    }


def forbidden_overlap_audit(
    docstore: Iterable[dict[str, Any]],
    forbidden_source_keys: set[str],
    *,
    allowed_group: str = "Reserve",
) -> dict[str, Any]:
    """验证 dev index 只含 Reserve，且不与正式评估 source 相交。"""

    wrong_group_chunks = 0
    overlapping_source_keys: set[str] = set()
    for row in docstore:
        if str(row.get("group") or "") != allowed_group:
            wrong_group_chunks += 1
        source_key = str(
            row.get("source_key")
            or (row.get("metadata") or {}).get("source_key")
            or ""
        )
        if source_key and source_key in forbidden_source_keys:
            overlapping_source_keys.add(source_key)
    return {
        "wrong_group_chunks": wrong_group_chunks,
        "forbidden_source_overlap": len(overlapping_source_keys),
        "overlapping_source_keys": sorted(overlapping_source_keys),
    }


def apply_dense_gate(
    metrics: dict[str, Any],
    overlap: dict[str, Any],
    *,
    recall_at_5_min: float = 0.70,
    recall_at_10_min: float = 0.80,
    zero_hit_source_rate_max: float = 0.05,
) -> dict[str, Any]:
    """应用预注册的 BGE 离线门槛。"""

    checks = {
        "recall_at_5": float(metrics["target_doc_recall_at_5"]) >= recall_at_5_min,
        "recall_at_10": float(metrics["target_doc_recall_at_10"]) >= recall_at_10_min,
        "zero_hit_source_rate": (
            float(metrics["zero_hit_source_rate"]) <= zero_hit_source_rate_max
        ),
        "forbidden_group_overlap": (
            int(overlap["wrong_group_chunks"]) == 0
            and int(overlap["forbidden_source_overlap"]) == 0
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def rank_passing_chunk_configs(
    per_config_dataset_metrics: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """只按 macro Recall@5、MRR、p95 延迟裁决，不读取攻击分数。"""

    ranked: list[dict[str, Any]] = []
    for config_id, dataset_metrics in per_config_dataset_metrics.items():
        if not dataset_metrics or not all(
            bool(metrics.get("gate", {}).get("passed"))
            for metrics in dataset_metrics.values()
        ):
            continue
        values = list(dataset_metrics.values())
        ranked.append(
            {
                "chunk_config_id": config_id,
                "macro_recall_at_5": sum(
                    float(row["target_doc_recall_at_5"]) for row in values
                )
                / len(values),
                "macro_mrr": sum(float(row["mrr"]) for row in values) / len(values),
                "macro_p95_latency_ms": sum(
                    float(row["latency_ms_p95"]) for row in values
                )
                / len(values),
            }
        )
    ranked.sort(
        key=lambda row: (
            -row["macro_recall_at_5"],
            -row["macro_mrr"],
            row["macro_p95_latency_ms"],
            row["chunk_config_id"],
        )
    )
    return ranked
