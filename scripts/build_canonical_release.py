"""Build the immutable paper release manifest from an explicit complete canonical suite."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.paper_figures import render_paper_figures  # noqa: E402
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import ensure_dir, read_json, read_jsonl, resolve_path, write_json  # noqa: E402
from src.utils.run_context import resolve_suite_run  # noqa: E402

DATASETS = ("edgar", "enron")
QUERY_CONTROLS = (
    "random_same_type_counterfactual",
    "independent_unpaired_query",
    "no_stealth_filter",
)


def _artifact(path: Path, root: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required canonical artifact is missing: {path}")
    return {
        "path": str(path.resolve()),
        "run_relative_path": path.relative_to(root).as_posix(),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _unique(root: Path, filename: str) -> Path:
    matches = sorted(path for path in root.rglob(filename) if path.is_file())
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one {filename} under {root}, found {len(matches)}")
    return matches[0]


def _paired_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    identity = dict(manifest.get("experiment_identity") or {})
    identity.pop("run_role", None)
    return identity


def collect_dataset_release(
    suite_id: str,
    dataset: str,
    *,
    render_figures: bool,
) -> dict[str, Any]:
    main_root, main_manifest, _ = resolve_suite_run(suite_id, dataset=dataset, run_role="main")
    control_root, control_manifest, _ = resolve_suite_run(
        suite_id, dataset=dataset, run_role="matched_control"
    )
    if _paired_identity(main_manifest) != _paired_identity(control_manifest):
        raise RuntimeError(f"Main/matched-control identity mismatch for {dataset}")

    report_path = _unique(main_root / "reports", f"{dataset}_final_report.json")
    source_path = _unique(main_root / "scores", f"{dataset}_pcv_scores_source_scores.jsonl")
    coverage_path = _unique(main_root / "scores", f"{dataset}_pcv_scores_source_coverage.jsonl")
    baseline_path = _unique(main_root / "baselines", f"{dataset}_baseline_comparison.jsonl")
    mechanism_path = _unique(main_root / "mechanisms", f"{dataset}_mechanism_report.json")
    defense_path = _unique(main_root / "defenses", f"{dataset}_defense_results.json")
    ablation_path = _unique(main_root / "diagnostics", f"{dataset}_p0_ablation.json")
    shortcut_path = _unique(main_root / "diagnostics", f"{dataset}_shortcut_controls.json")
    report = read_json(report_path)
    expected_whitelist = str((main_manifest.get("experiment_identity") or {}).get("source_whitelist_hash") or "")
    if report.get("source_whitelist_hash") != expected_whitelist:
        raise RuntimeError(f"Report/run source whitelist mismatch for {dataset}")
    ablation = read_json(ablation_path)
    if ablation.get("source_whitelist_hash") != expected_whitelist:
        raise RuntimeError(f"Ablation/run source whitelist mismatch for {dataset}")

    query_controls: dict[str, Any] = {}
    for variant in QUERY_CONTROLS:
        query_controls[variant] = {
            "query_manifest": _artifact(
                main_root / "query_controls" / dataset / variant / "control_manifest.json",
                main_root,
            ),
            "rag_responses": _artifact(
                main_root / "query_control_responses" / variant / "rag_responses.jsonl",
                main_root,
            ),
            "source_scores": _artifact(
                main_root / "query_control_scores" / variant / "pcv_scores_source_scores.jsonl",
                main_root,
            ),
            "analysis": _artifact(
                _unique(main_root / "diagnostics", f"{dataset}_{variant}_query_control.json"),
                main_root,
            ),
        }

    release_dir = ensure_dir(resolve_path("outputs/releases") / suite_id / dataset)
    figure_artifacts: list[dict[str, Any]] = []
    if render_figures:
        baseline_rows = list(read_jsonl(baseline_path))
        produced = render_paper_figures(
            report,
            list(read_jsonl(source_path)),
            baseline_rows,
            release_dir,
            dataset=dataset,
        )
        figure_artifacts = [{
            "path": str(Path(path).resolve()),
            "release_relative_path": Path(path).relative_to(release_dir).as_posix(),
            "size": Path(path).stat().st_size,
            "sha256": sha256_file(path),
        } for path in produced]

    return {
        "dataset": dataset,
        "source_whitelist_hash": expected_whitelist,
        "main_run": {
            "run_id": main_manifest.get("run_id"),
            "root": str(main_root.resolve()),
            "manifest": _artifact(main_root / "run_manifest.json", main_root),
        },
        "matched_control_run": {
            "run_id": control_manifest.get("run_id"),
            "root": str(control_root.resolve()),
            "manifest": _artifact(control_root / "run_manifest.json", control_root),
        },
        "artifacts": {
            "final_report": _artifact(report_path, main_root),
            "source_scores": _artifact(source_path, main_root),
            "source_coverage": _artifact(coverage_path, main_root),
            "baseline_comparison": _artifact(baseline_path, main_root),
            "mechanism": _artifact(mechanism_path, main_root),
            "defense": _artifact(defense_path, main_root),
            "offline_ablation": _artifact(ablation_path, main_root),
            "shortcut_controls": _artifact(shortcut_path, main_root),
            "query_controls": query_controls,
            "paper_figures": figure_artifacts,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an explicit canonical paper release")
    parser.add_argument("--suite-id", required=True)
    parser.add_argument("--no-figures", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    suite_path = resolve_path("outputs/releases") / args.suite_id / "suite_manifest.json"
    if not suite_path.is_file():
        raise FileNotFoundError(f"Suite manifest not found: {suite_path}")
    suite = read_json(suite_path)
    if suite.get("status") != "canonical" or suite.get("missing_cells"):
        raise RuntimeError("Canonical release requires all preregistered suite cells")
    datasets = {
        dataset: collect_dataset_release(
            args.suite_id,
            dataset,
            render_figures=not args.no_figures,
        )
        for dataset in DATASETS
    }
    manifest = {
        "suite_id": args.suite_id,
        "status": "canonical",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selection_rule": suite.get("selection_rule"),
        "release_commit": suite.get("release_commit"),
        "suite_manifest": {
            "path": str(suite_path.resolve()),
            "sha256": sha256_file(suite_path),
        },
        "datasets": datasets,
        "dataset_binding_hash": sha256_obj({
            dataset: {
                "main": value["main_run"]["run_id"],
                "matched_control": value["matched_control_run"]["run_id"],
                "source_whitelist_hash": value["source_whitelist_hash"],
            }
            for dataset, value in datasets.items()
        }),
    }
    output = suite_path.parent / "canonical_release.json"
    write_json(manifest, output)
    print(f"[saved] {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
