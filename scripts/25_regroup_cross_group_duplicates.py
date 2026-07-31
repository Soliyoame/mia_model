"""Deterministically repair cross-group near-duplicate clusters before API use."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.v20_release_controls import source_key  # noqa: E402
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import read_json, read_jsonl, write_json, write_jsonl  # noqa: E402


GROUP_FILES = {
    "KB_Member": "kb_member.jsonl",
    "True_Non_Member": "true_non_member.jsonl",
    "Reserve": "reserve.jsonl",
}


def _components(pairs: list[dict]) -> list[set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for row in pairs:
        left = str(row["left_source_key"])
        right = str(row["right_source_key"])
        graph[left].add(right)
        graph[right].add(left)
    seen: set[str] = set()
    components = []
    for root in sorted(graph):
        if root in seen:
            continue
        stack = [root]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            component.add(current)
            stack.extend(sorted(graph[current] - seen))
        components.append(component)
    return components


def _backup(path: Path, root: Path) -> None:
    if not path.is_file():
        return
    relative = path.relative_to(PROJECT_ROOT)
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)


def _refresh_output_manifest(
    manifest_path: Path,
    output_path: Path,
    *,
    extra: dict | None = None,
) -> None:
    if not manifest_path.is_file():
        return
    manifest = read_json(manifest_path)
    digest = sha256_file(output_path)
    for key in (
        "output_hash",
        "queries_hash",
        "facts_hash",
        "claims_hash",
        "benchmark_hash",
    ):
        if key in manifest:
            manifest[key] = digest
    manifest["post_regroup_output_hash"] = digest
    manifest["post_regroup_at"] = datetime.now(timezone.utc).isoformat()
    if extra:
        manifest.update(extra)
    write_json(manifest, manifest_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair v20 cross-group duplicate clusters")
    parser.add_argument("--dataset", default="edgar")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the deterministic regrouping proposal without changing artifacts",
    )
    args = parser.parse_args()
    dataset = args.dataset
    split_dir = PROJECT_ROOT / "artifacts" / "v6_3" / "splits" / dataset
    audit_path = (
        PROJECT_ROOT
        / "artifacts"
        / "v20"
        / "release_controls"
        / f"{dataset}_near_duplicate_audit.json"
    )
    audit = read_json(audit_path)
    cross_pairs = list(audit.get("cross_group_overlap") or [])
    if not cross_pairs:
        print(f"[unchanged] {dataset}: no cross-group duplicate cluster")
        return 0
    rows_by_group = {
        group: list(read_jsonl(split_dir / filename))
        for group, filename in GROUP_FILES.items()
    }
    source_groups = {}
    for group, rows in rows_by_group.items():
        for row in rows:
            key = source_key(row)
            previous = source_groups.setdefault(key, group)
            if previous != group:
                raise RuntimeError(f"Source already crosses split groups: {key}")
    duplicate_keys = {
        str(row[field])
        for row in audit.get("pairs", [])
        for field in ("left_source_key", "right_source_key")
    }
    pilot_keys: set[str] = set()
    budget_path = (
        PROJECT_ROOT
        / "artifacts"
        / "v6_3"
        / "query_controls"
        / dataset
        / "llama-3.1-70b-instruct-pilot"
        / "budget.json"
    )
    if budget_path.is_file():
        budget = read_json(budget_path)
        for keys in (budget.get("selected_source_keys") or {}).values():
            pilot_keys.update(str(key) for key in keys)
    assignments = dict(source_groups)
    decisions = []
    for component in _components(cross_pairs):
        groups = sorted({source_groups[key] for key in component})
        if len(groups) == 1:
            continue
        target_index = int(
            sha256_obj(
                {"seed": args.seed, "cluster": sorted(component)}
            )[:16],
            16,
        ) % len(groups)
        target_group = groups[target_index]
        before = Counter(source_groups[key] for key in component)
        for key in component:
            assignments[key] = target_group
        delta = Counter({target_group: len(component)})
        delta.subtract(before)
        swaps = []
        overfull = sorted(
            group for group, value in delta.items() if value > 0
        )
        underfull = sorted(
            group for group, value in delta.items() if value < 0
        )
        for donor_group in overfull:
            surplus = int(delta[donor_group])
            for _ in range(surplus):
                receiver_group = next(
                    group for group in underfull if delta[group] < 0
                )
                candidates = [
                    key
                    for key, group in source_groups.items()
                    if group == donor_group
                    and key not in duplicate_keys
                    and key not in pilot_keys
                    and assignments[key] == donor_group
                ]
                if not candidates:
                    raise RuntimeError("No safe singleton available for exact-count swap")
                chosen = min(
                    candidates,
                    key=lambda key: sha256_obj(
                        {
                            "seed": args.seed,
                            "cluster": sorted(component),
                            "singleton": key,
                            "receiver": receiver_group,
                        }
                    ),
                )
                assignments[chosen] = receiver_group
                delta[donor_group] -= 1
                delta[receiver_group] += 1
                swaps.append(
                    {
                        "source_key": chosen,
                        "from": donor_group,
                        "to": receiver_group,
                    }
                )
        if any(delta.values()):
            raise RuntimeError(f"Unable to preserve exact split counts: {dict(delta)}")
        decisions.append(
            {
                "cluster": sorted(component),
                "original_groups": dict(before),
                "assigned_group": target_group,
                "singleton_swaps": swaps,
            }
        )
    changed = {
        key: {"from": source_groups[key], "to": group}
        for key, group in assignments.items()
        if source_groups[key] != group
    }
    final_counts = Counter(assignments.values())
    if final_counts != Counter(
        {"KB_Member": 500, "True_Non_Member": 500, "Reserve": 250}
    ):
        raise RuntimeError(f"Regrouping changed target counts: {dict(final_counts)}")
    if args.dry_run:
        print(
            json.dumps(
                {
                    "protocol_version": "pcv-mia-v20",
                    "dataset": dataset,
                    "seed": args.seed,
                    "decisions": decisions,
                    "changed_sources": changed,
                    "final_source_counts": dict(final_counts),
                    "api_calls_made": 0,
                    "dry_run": True,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    backup_root = (
        PROJECT_ROOT
        / "legacy"
        / "pre_response_regroup_20260731"
        / dataset
    )
    core_paths = [
        *(split_dir / filename for filename in GROUP_FILES.values()),
        split_dir / "split_manifest.json",
        PROJECT_ROOT / "artifacts" / "v6_3" / "benchmarks" / f"{dataset}_attack_benchmark.jsonl",
        PROJECT_ROOT / "artifacts" / "v6_3" / "benchmarks" / f"{dataset}_benchmark_manifest.json",
        PROJECT_ROOT / "artifacts" / "v6_3" / "benchmarks" / f"{dataset}_attack_benchmark.sha256",
        PROJECT_ROOT / "artifacts" / "v6_3" / "facts" / f"{dataset}_facts.jsonl",
        PROJECT_ROOT / "artifacts" / "v6_3" / "paired_claims" / f"{dataset}_paired_claims.jsonl",
        PROJECT_ROOT / "artifacts" / "v6_3" / "paired_queries" / f"{dataset}_paired_queries.jsonl",
        PROJECT_ROOT / "artifacts" / "v6_3" / "stealth_filtered_queries" / f"{dataset}_paired_queries.jsonl",
    ]
    for path in core_paths:
        _backup(path, backup_root)
    all_rows = [row for rows in rows_by_group.values() for row in rows]
    rewritten: dict[str, list[dict]] = defaultdict(list)
    for row in all_rows:
        updated = dict(row)
        key = source_key(row)
        group = assignments[key]
        updated["group"] = group
        metadata = dict(updated.get("metadata") or {})
        metadata["in_knowledge_base"] = group == "KB_Member"
        updated["metadata"] = metadata
        rewritten[group].append(updated)
    for group, filename in GROUP_FILES.items():
        ordered = sorted(
            rewritten[group],
            key=lambda row: (
                source_key(row),
                str(row.get("doc_id") or ""),
            ),
        )
        write_jsonl(ordered, split_dir / filename)
    split_manifest_path = split_dir / "split_manifest.json"
    split_manifest = read_json(split_manifest_path)
    split_manifest["counts"] = {
        group: len(rewritten[group]) for group in GROUP_FILES
    } | {"Spoof_Seed": 0}
    split_manifest["source_counts"] = {
        group: len({source_key(row) for row in rewritten[group]})
        for group in GROUP_FILES
    } | {"Spoof_Seed": 0}
    hashes = {
        group: sorted(str(row.get("text_hash") or "") for row in rewritten[group])
        for group in GROUP_FILES
    } | {"Spoof_Seed": []}
    split_manifest["hashes"] = hashes
    split_manifest["hash_summary"] = {
        group: sha256_obj(values) for group, values in hashes.items()
    }
    split_manifest["near_duplicate_regrouping"] = {
        "seed": args.seed,
        "decisions": decisions,
        "changed_sources": changed,
        "pre_regroup_audit_hash": sha256_file(audit_path),
        "backup_root": str(backup_root),
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(split_manifest, split_manifest_path)
    downstream = [
        (
            PROJECT_ROOT / "artifacts" / "v6_3" / "benchmarks" / f"{dataset}_attack_benchmark.jsonl",
            PROJECT_ROOT / "artifacts" / "v6_3" / "benchmarks" / f"{dataset}_benchmark_manifest.json",
        ),
        (
            PROJECT_ROOT / "artifacts" / "v6_3" / "facts" / f"{dataset}_facts.jsonl",
            PROJECT_ROOT / "artifacts" / "v6_3" / "facts" / f"{dataset}_facts.manifest.json",
        ),
        (
            PROJECT_ROOT / "artifacts" / "v6_3" / "paired_claims" / f"{dataset}_paired_claims.jsonl",
            PROJECT_ROOT / "artifacts" / "v6_3" / "paired_claims" / f"{dataset}_paired_claims.manifest.json",
        ),
        (
            PROJECT_ROOT / "artifacts" / "v6_3" / "paired_queries" / f"{dataset}_paired_queries.jsonl",
            PROJECT_ROOT / "artifacts" / "v6_3" / "paired_queries" / f"{dataset}_paired_queries.manifest.json",
        ),
        (
            PROJECT_ROOT / "artifacts" / "v6_3" / "stealth_filtered_queries" / f"{dataset}_paired_queries.jsonl",
            PROJECT_ROOT / "artifacts" / "v6_3" / "stealth_filtered_queries" / f"{dataset}_paired_queries.manifest.json",
        ),
    ]
    for output_path, manifest_path in downstream:
        if not output_path.is_file():
            continue
        output_rows = []
        for row in read_jsonl(output_path):
            updated = dict(row)
            key = source_key(row)
            if key in assignments:
                updated["group"] = assignments[key]
            output_rows.append(updated)
        write_jsonl(output_rows, output_path)
        _refresh_output_manifest(
            manifest_path,
            output_path,
            extra={
                "near_duplicate_regrouping_hash": sha256_obj(changed),
                "split_manifest_hash": sha256_file(split_manifest_path),
            },
        )
    benchmark_path = downstream[0][0]
    benchmark_hash = sha256_file(benchmark_path)
    benchmark_manifest_path = downstream[0][1]
    benchmark_manifest = read_json(benchmark_manifest_path)
    benchmark_manifest["benchmark_hash"] = benchmark_hash
    benchmark_manifest["input_hashes"] = {
        group: sha256_file(split_dir / filename)
        for group, filename in GROUP_FILES.items()
    }
    benchmark_manifest["source_counts"] = {
        group: final_counts[group] for group in GROUP_FILES
    }
    benchmark_manifest["split_manifest_hash"] = sha256_file(split_manifest_path)
    write_json(benchmark_manifest, benchmark_manifest_path)
    (benchmark_path.with_suffix(".sha256")).write_text(
        benchmark_hash + "\n",
        encoding="utf-8",
    )
    query_manifest_path = downstream[-1][1]
    query_manifest = read_json(query_manifest_path)
    query_manifest["benchmark_hash"] = benchmark_hash
    query_manifest["benchmark_manifest_hash"] = sha256_file(
        benchmark_manifest_path
    )
    query_manifest["output_hash"] = sha256_file(downstream[-1][0])
    write_json(query_manifest, query_manifest_path)
    regroup_manifest = {
        "protocol_version": "pcv-mia-v20",
        "dataset": dataset,
        "seed": args.seed,
        "decisions": decisions,
        "changed_sources": changed,
        "final_source_counts": dict(final_counts),
        "backup_root": str(backup_root),
        "api_calls_made": 0,
    }
    output = (
        PROJECT_ROOT
        / "artifacts"
        / "v20"
        / "release_controls"
        / f"{dataset}_regroup_manifest.json"
    )
    write_json(regroup_manifest, output)
    print(f"[saved] {output} changed_sources={len(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
