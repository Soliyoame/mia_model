"""Verify the current offline artifacts without calling any model API."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import read_jsonl, write_json  # noqa: E402
from src.paired_claims.validator import validate_query_pair  # noqa: E402


DATASETS = ("edgar", "enron", "pubmed")
GROUP_FILES = {
    "KB_Member": ("kb_member.jsonl", 500),
    "True_Non_Member": ("true_non_member.jsonl", 500),
    "Reserve": ("reserve.jsonl", 250),
}
PAIRS_PER_SOURCE = 3
QUERIES_PER_SOURCE = 6
ANNOTATION_FIELDS = ("human_pair_valid", "human_failure_reason", "audit_notes")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify current offline artifact integrity")
    parser.add_argument("--artifacts-dir", default="artifacts/v6_3")
    parser.add_argument(
        "--output",
        default="artifacts/v6_3/audits/offline_integrity_report.json",
        help="JSON report path; pass an empty string to avoid writing a report",
    )
    return parser.parse_args()


def _source_key(row: dict[str, Any]) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return str(
        row.get("source_key")
        or metadata.get("source_key")
        or row.get("source_id")
        or row.get("doc_id")
        or ""
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _load_splits(dataset: str, artifacts_dir: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    split_dir = artifacts_dir / "splits" / dataset
    sources_by_group: dict[str, set[str]] = {}
    rows_by_group: dict[str, int] = {}
    doc_ids_by_group: dict[str, Counter[str]] = {}
    for expected_group, (filename, expected_sources) in GROUP_FILES.items():
        rows = list(read_jsonl(split_dir / filename))
        keys = {_source_key(row) for row in rows}
        _require("" not in keys, f"{dataset}/{expected_group}: split row is missing source identity")
        _require(
            all(str(row.get("group")) == expected_group for row in rows),
            f"{dataset}/{expected_group}: split contains a mismatched group label",
        )
        _require(
            len(keys) == expected_sources,
            f"{dataset}/{expected_group}: expected {expected_sources} sources, found {len(keys)}",
        )
        sources_by_group[expected_group] = keys
        rows_by_group[expected_group] = len(rows)
        doc_ids_by_group[expected_group] = Counter(str(row.get("doc_id") or "") for row in rows)

    group_names = sorted(sources_by_group)
    for index, left in enumerate(group_names):
        for right in group_names[index + 1 :]:
            overlap = sources_by_group[left] & sources_by_group[right]
            _require(not overlap, f"{dataset}: source overlap between {left} and {right}: {len(overlap)}")

    return sources_by_group, {
        "source_counts": {group: len(keys) for group, keys in sources_by_group.items()},
        "row_counts": rows_by_group,
        "doc_ids_by_group": doc_ids_by_group,
    }


def audit_fixed_queries(
    dataset: str,
    rows: Iterable[dict[str, Any]],
    sources_by_group: dict[str, set[str]],
) -> dict[str, Any]:
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    query_ids: set[str] = set()
    pair_ids: set[str] = set()
    total_rows = 0
    for row in rows:
        total_rows += 1
        query_id = str(row.get("query_id") or "")
        _require(query_id and query_id not in query_ids, f"{dataset}: missing/duplicate query_id {query_id!r}")
        query_ids.add(query_id)
        _require(row.get("accepted") is True, f"{dataset}: accepted query file contains a rejected row")
        source = _source_key(row)
        _require(bool(source), f"{dataset}: query {query_id} is missing source identity")
        by_source[source].append(row)
        pair_ids.add(str(row.get("pair_id") or ""))

    expected_sources = set().union(*sources_by_group.values())
    _require(set(by_source) == expected_sources, f"{dataset}: query sources do not equal the formal split sources")
    expected_query_count = len(expected_sources) * QUERIES_PER_SOURCE
    _require(
        total_rows == expected_query_count,
        f"{dataset}: expected {expected_query_count} queries",
    )

    source_counts_by_group: Counter[str] = Counter()
    duplicate_query_text_sources = 0
    for source, source_rows in by_source.items():
        _require(
            len(source_rows) == QUERIES_PER_SOURCE,
            f"{dataset}/{source}: expected {QUERIES_PER_SOURCE} queries, found {len(source_rows)}",
        )
        queries = [str(row.get("query") or "") for row in source_rows]
        _require(all(queries), f"{dataset}/{source}: empty query text")
        if len(set(queries)) != QUERIES_PER_SOURCE:
            duplicate_query_text_sources += 1

        expected_group = next(group for group, sources in sources_by_group.items() if source in sources)
        _require(
            all(str(row.get("group")) == expected_group for row in source_rows),
            f"{dataset}/{source}: query group does not match split group",
        )
        source_counts_by_group[expected_group] += 1

        by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in source_rows:
            pair_id = str(row.get("pair_id") or "")
            _require(bool(pair_id), f"{dataset}/{source}: query is missing pair_id")
            by_pair[pair_id].append(row)
            _require(
                int(row.get("fixed_budget_pairs_per_source") or 0) == PAIRS_PER_SOURCE,
                f"{dataset}/{source}: fixed-budget field is not {PAIRS_PER_SOURCE}",
            )
            _require(
                int(row.get("logical_victim_calls_per_source") or 0) == QUERIES_PER_SOURCE,
                f"{dataset}/{source}: logical call budget is not {QUERIES_PER_SOURCE}",
            )
        _require(
            len(by_pair) == PAIRS_PER_SOURCE,
            f"{dataset}/{source}: expected {PAIRS_PER_SOURCE} query pairs",
        )
        for pair_id, pair_rows in by_pair.items():
            by_type = {str(row.get("claim_type")): row for row in pair_rows}
            _require(
                len(pair_rows) == 2 and set(by_type) == {"true", "counterfactual"},
                f"{dataset}/{source}/{pair_id}: pair is not a complete Q+/Q- pair",
            )
            true_row = by_type["true"]
            false_row = by_type["counterfactual"]
            original = str(true_row.get("original_entity") or true_row.get("expected_entity") or "")
            counterfactual = str(false_row.get("counterfactual_entity") or "")
            _require(original and counterfactual and original != counterfactual, f"{dataset}/{pair_id}: invalid entities")
            validation = validate_query_pair(
                str(true_row.get("query") or ""),
                str(false_row.get("query") or ""),
                original,
                counterfactual,
            )
            _require(
                validation.valid,
                f"{dataset}/{pair_id}: Q+/Q- differ outside the entity slot: {validation.reasons}",
            )

    _require(
        duplicate_query_text_sources == 0,
        f"{dataset}: {duplicate_query_text_sources} sources contain duplicate query text",
    )

    return {
        "query_count": total_rows,
        "query_id_count": len(query_ids),
        "pair_count": len(pair_ids),
        "source_count": len(by_source),
        "source_counts_by_group": dict(source_counts_by_group),
        "queries_per_source": QUERIES_PER_SOURCE,
        "pairs_per_source": PAIRS_PER_SOURCE,
        "duplicate_query_text_sources": duplicate_query_text_sources,
        "source_plan_hash": sha256_obj(sorted(by_source)),
        "query_plan_hash": sha256_obj(sorted(query_ids)),
    }


def _audit_query_manifest(dataset: str, artifacts_dir: Path) -> dict[str, Any]:
    path = artifacts_dir / "stealth_filtered_queries" / f"{dataset}_paired_queries.manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    fixed = manifest.get("fixed_budget") or {}
    expected_query_count = 1_250 * QUERIES_PER_SOURCE
    expected_pair_count = 1_250 * PAIRS_PER_SOURCE
    _require(
        int(manifest.get("accepted") or 0) == expected_query_count,
        f"{dataset}: manifest accepted != {expected_query_count}",
    )
    _require(int(fixed.get("eligible_sources") or 0) == 1_250, f"{dataset}: manifest source count != 1,250")
    _require(
        int(fixed.get("selected_pairs") or 0) == expected_pair_count,
        f"{dataset}: manifest pair count != {expected_pair_count}",
    )
    _require(
        int(fixed.get("pairs_per_source") or 0) == PAIRS_PER_SOURCE,
        f"{dataset}: manifest pairs/source != {PAIRS_PER_SOURCE}",
    )
    _require(
        int(fixed.get("queries_per_source") or 0) == QUERIES_PER_SOURCE,
        f"{dataset}: manifest queries/source != {QUERIES_PER_SOURCE}",
    )
    _require(not fixed.get("insufficient_sources"), f"{dataset}: manifest has insufficient sources")
    _require(fixed.get("query_text_uniqueness_enforced") is True, f"{dataset}: query-text uniqueness is not frozen")
    return {
        "fixed_budget_plan_hash": fixed.get("fixed_budget_plan_hash"),
        "embedding_model": manifest.get("embedding_model"),
        "embedding_local_files_only": manifest.get("embedding_local_files_only"),
        "embedding_batch_size": manifest.get("embedding_batch_size"),
    }


def _blank_annotation_template_hash(rows: Iterable[dict[str, Any]]) -> str:
    """计算仅清空人工字段后的原始模板哈希，不改动标注文件。"""
    digest = hashlib.sha256()
    for row in rows:
        template_row = dict(row)
        for field in ANNOTATION_FIELDS:
            template_row[field] = ""
        digest.update(json.dumps(template_row, ensure_ascii=False, sort_keys=False).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _audit_annotation_templates(dataset: str, artifacts_dir: Path) -> dict[str, Any]:
    audit_dir = artifacts_dir / "audits" / "claim_pair_audit"
    path_a = audit_dir / f"{dataset}_claim_pair_audit_annotator_a.jsonl"
    path_b = audit_dir / f"{dataset}_claim_pair_audit_annotator_b.jsonl"
    manifest_path = audit_dir / f"{dataset}_claim_pair_audit_manifest.json"
    rows_a = list(read_jsonl(path_a))
    rows_b = list(read_jsonl(path_b))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    _require(len(rows_a) == len(rows_b) == 200, f"{dataset}: annotator files must contain 200 rows each")
    by_a = {str(row.get("audit_id") or ""): row for row in rows_a}
    by_b = {str(row.get("audit_id") or ""): row for row in rows_b}
    _require(len(by_a) == len(by_b) == 200 and set(by_a) == set(by_b), f"{dataset}: A/B samples differ")
    _require([row["audit_id"] for row in rows_a] != [row["audit_id"] for row in rows_b], f"{dataset}: A/B order is not blinded")
    immutable = (
        "dataset",
        "source_key",
        "entity_type",
        "original_entity",
        "counterfactual_entity",
        "true_claim",
        "counterfactual_claim",
    )
    for audit_id in by_a:
        left, right = by_a[audit_id], by_b[audit_id]
        _require(str(left.get("annotator_role")) == "A", f"{dataset}: invalid annotator A role")
        _require(str(right.get("annotator_role")) == "B", f"{dataset}: invalid annotator B role")
        _require(all(left.get(field) == right.get(field) for field in immutable), f"{dataset}/{audit_id}: A/B content drift")

    filled_a = sum(bool(str(row.get("human_pair_valid") or "").strip()) for row in rows_a)
    filled_b = sum(bool(str(row.get("human_pair_valid") or "").strip()) for row in rows_b)
    blank_templates = all(
        not str(row.get(field) or "").strip()
        for row in rows_a + rows_b
        for field in ANNOTATION_FIELDS
    )
    allowed_labels = {str(label).strip().lower() for label in manifest.get("annotation_labels") or []}
    for role, rows in (("A", rows_a), ("B", rows_b)):
        for row in rows:
            label = str(row.get("human_pair_valid") or "").strip().lower()
            _require(not label or label in allowed_labels, f"{dataset}: annotator {role} has invalid label {label!r}")

    template_hash_a = _blank_annotation_template_hash(rows_a)
    template_hash_b = _blank_annotation_template_hash(rows_b)
    _require(template_hash_a == manifest.get("annotator_a_hash"), f"{dataset}: annotator A template hash drift")
    _require(template_hash_b == manifest.get("annotator_b_hash"), f"{dataset}: annotator B template hash drift")
    _require(
        sha256_obj(sorted(by_a)) == manifest.get("sample_whitelist_hash"),
        f"{dataset}: audit sample whitelist hash drift",
    )
    return {
        "rows_per_annotator": 200,
        "sample_source_count": len({_source_key(row) for row in rows_a}),
        "same_sample_ids": True,
        "different_order": True,
        "annotator_a_hash": sha256_file(path_a),
        "annotator_b_hash": sha256_file(path_b),
        "annotator_a_template_hash": template_hash_a,
        "annotator_b_template_hash": template_hash_b,
        "template_hashes_verified": True,
        "sample_whitelist_hash": manifest.get("sample_whitelist_hash"),
        "filled_labels": {"A": filled_a, "B": filled_b},
        "annotation_status": "pending_human_annotation" if blank_templates else "annotations_present",
    }


def _audit_enron_dense_index(artifacts_dir: Path, split_meta: dict[str, Any]) -> dict[str, Any]:
    index_dir = artifacts_dir / "indexes" / "enron" / "dense"
    docstore_path = index_dir / "docstore.jsonl"
    index_path = index_dir / "faiss.index"
    manifest = json.loads((index_dir / "index_manifest.json").read_text(encoding="utf-8"))
    docstore_rows = list(read_jsonl(docstore_path))
    docstore_ids = Counter(str(row.get("doc_id") or "") for row in docstore_rows)
    kb_ids = split_meta["doc_ids_by_group"]["KB_Member"]
    forbidden_ids = (
        set(split_meta["doc_ids_by_group"]["True_Non_Member"])
        | set(split_meta["doc_ids_by_group"]["Reserve"])
    )
    _require(all(row.get("group") == "KB_Member" for row in docstore_rows), "enron dense index contains a forbidden group")
    _require(docstore_ids == kb_ids, "enron dense docstore does not exactly match the KB split")
    _require(not (set(docstore_ids) & forbidden_ids), "enron dense index overlaps a forbidden split")
    _require(sha256_file(docstore_path) == manifest.get("docstore_hash"), "enron dense docstore hash drift")
    _require(sha256_file(index_path) == manifest.get("index_hash"), "enron dense index hash drift")
    boundary = manifest.get("security_boundary") or {}
    _require(boundary.get("allowed_groups") == ["KB_Member"], "enron dense manifest has an invalid allowlist")
    _require(manifest.get("retriever_backend") == "dense", "enron retriever backend is not dense")
    _require(
        manifest.get("retriever_id") == "sentence-transformers/all-MiniLM-L6-v2",
        "enron dense retriever ID drift",
    )
    return {
        "document_count": len(docstore_rows),
        "kb_document_match": True,
        "forbidden_document_overlap": 0,
        "retriever_id": manifest.get("retriever_id"),
        "embedding_backend": manifest.get("embedding_backend"),
        "docstore_hash": manifest.get("docstore_hash"),
        "index_hash": manifest.get("index_hash"),
    }


def verify(artifacts_dir: Path) -> dict[str, Any]:
    dataset_reports: dict[str, Any] = {}
    audit_reports: dict[str, Any] = {}
    split_metadata: dict[str, dict[str, Any]] = {}
    for dataset in DATASETS:
        sources_by_group, split_meta = _load_splits(dataset, artifacts_dir)
        split_metadata[dataset] = split_meta
        query_path = artifacts_dir / "stealth_filtered_queries" / f"{dataset}_paired_queries.jsonl"
        query_report = audit_fixed_queries(dataset, read_jsonl(query_path), sources_by_group)
        query_report.update(_audit_query_manifest(dataset, artifacts_dir))
        dataset_reports[dataset] = {
            "split_source_counts": {group: len(values) for group, values in sources_by_group.items()},
            "split_row_counts": split_meta["row_counts"],
            "queries": query_report,
        }
        audit_reports[dataset] = _audit_annotation_templates(dataset, artifacts_dir)

    return {
        "status": "passed",
        "protocol": "v19_offline_integrity_v1",
        "api_calls_performed": 0,
        "datasets": dataset_reports,
        "claim_pair_audits": audit_reports,
        "enron_dense_index": _audit_enron_dense_index(artifacts_dir, split_metadata["enron"]),
        "human_quality_gate": {
            "status": "pending",
            "reason": "Two independent human annotation files have not been filled and returned.",
            "minimum_double_pass_rate": 0.90,
            "minimum_cohen_kappa": 0.80,
        },
    }


def main() -> int:
    args = parse_args()
    artifacts_dir = Path(args.artifacts_dir).resolve()
    report = verify(artifacts_dir)
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        write_json(report, output)
        print(f"[saved] {output}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
