"""统一实体类型策略的 inventory、回放、pilot、审计与 release 入口。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.attack.entity_type_policy import (  # noqa: E402
    ENTITY_TYPE_POLICY_SHA256,
    ENTITY_TYPE_POLICY_VERSION,
)
from src.attack.entity_extractor import EXTRACTOR_VERSION  # noqa: E402
from src.attack.semantic_entity_resolver import (  # noqa: E402
    load_semantic_entity_resolver,
)
from src.paired_claims.claim_generator import (  # noqa: E402
    generate_paired_claims_file,
)
from src.paired_claims.validator import VALIDATOR_VERSION  # noqa: E402
from src.prepare.eligibility_scan import (  # noqa: E402
    run_pipeline_wave,
    validate_completed_wave,
)
from src.prepare.entity_policy_release import (  # noqa: E402
    runtime_tree_sha256,
)
from src.prepare.formal_evidence_scope import (  # noqa: E402
    FORMAL_EVIDENCE_SCOPE_SHA256,
    FORMAL_EVIDENCE_SCOPE_VERSION,
)
from src.prepare.formal_dataset_role_scope import (  # noqa: E402
    capacity_promotion_config,
    validate_audit_report_role,
)
from src.prepare.enron_capacity_promotion import (  # noqa: E402
    build_enron_capacity_promotion,
    validate_enron_capacity_promotion,
)
from src.prepare.entity_policy_validation import (  # noqa: E402
    HISTORICAL_REPLAY_PROTOCOL,
    PILOT_COHORTS,
    PILOT_PROTOCOL,
    build_dataset_report,
    build_historical_inventory,
    evaluate_audit,
    freeze_pilot_cohorts,
    freeze_release_gate,
    prepare_blinded_audit,
    validate_dataset_report,
    validate_historical_inventory,
    validate_pilot_plan,
    validate_release_gate,
)
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import (  # noqa: E402
    ensure_dir,
    load_yaml,
    read_json,
    read_jsonl,
    write_json,
)


DEFAULT_WORKSPACE = PROJECT_ROOT / "artifacts" / "v21" / "entity_policy_r1"
DEFAULT_RELEASE_WORKSPACE = (
    PROJECT_ROOT / "artifacts" / "v21" / "entity_policy_r3"
)
DEFAULT_INVENTORY = DEFAULT_WORKSPACE / "inventory" / "historical_inventory.json"
DEFAULT_PILOT_PLAN = DEFAULT_WORKSPACE / "pilots" / "pilot_cohorts.json"
DEFAULT_ATTACK_CONFIG = PROJECT_ROOT / "configs" / "pcv_attack_v6_3.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the v21 entity policy before any formal full scan"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory")
    inventory.add_argument("--output", default=str(DEFAULT_INVENTORY))

    freeze_pilots = subparsers.add_parser("freeze-pilots")
    freeze_pilots.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    freeze_pilots.add_argument("--output", default=str(DEFAULT_PILOT_PLAN))

    for command in ("replay", "pilot"):
        stage = subparsers.add_parser(command)
        stage.add_argument(
            "--dataset",
            choices=["edgar", "enron", "pubmed"],
            required=True,
        )
        stage.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
        stage.add_argument("--attack-config", default=str(DEFAULT_ATTACK_CONFIG))
        stage.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
        stage.add_argument("--resume", action="store_true")
        stage.add_argument("--max-new-waves", type=int, default=None)
        if command == "pilot":
            stage.add_argument("--pilot-plan", default=str(DEFAULT_PILOT_PLAN))
            stage.add_argument("--cohort", choices=list(PILOT_COHORTS), required=True)

    audit = subparsers.add_parser("prepare-audit")
    audit.add_argument("--accepted-claims", action="append", default=[])
    audit.add_argument(
        "--report",
        action="append",
        default=[],
        help=(
            "Role-validated frozen replay/pilot report whose claim_paths "
            "enter the audit."
        ),
    )
    audit.add_argument("--hard-negatives", action="append", default=[])
    audit.add_argument(
        "--output-dir",
        default=str(DEFAULT_RELEASE_WORKSPACE / "audit"),
    )

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    finalize.add_argument("--replay-report", action="append", required=True)
    finalize.add_argument("--pilot-report", action="append", required=True)
    finalize.add_argument("--audit-manifest", required=True)
    finalize.add_argument("--assistant-labels", required=True)
    finalize.add_argument("--user-review", required=True)
    finalize.add_argument(
        "--output",
        default=str(
            DEFAULT_RELEASE_WORKSPACE
            / "release"
            / "entity_policy_release_gate.json"
        ),
    )

    check = subparsers.add_parser("check-release")
    check.add_argument("--release-gate", required=True)

    promote = subparsers.add_parser("promote-enron-capacity")
    promote.add_argument("--release-gate", required=True)
    promote.add_argument(
        "--output",
        default=str(
            PROJECT_ROOT / capacity_promotion_config()["output_path"]
        ),
    )

    check_promotion = subparsers.add_parser("check-enron-promotion")
    check_promotion.add_argument("--promotion", required=True)
    return parser.parse_args()


def _code_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _load_attack_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    config = load_yaml(config_path)
    policy = (config.get("fact_extraction") or {}).get("entity_type_policy") or {}
    if (
        policy.get("protocol") != ENTITY_TYPE_POLICY_VERSION
        or policy.get("sha256") != ENTITY_TYPE_POLICY_SHA256
    ):
        raise RuntimeError("Attack config entity policy identity mismatch")
    return config


def _selected_candidates(
    benchmark_path: str | Path,
    source_keys: Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    selected = set(str(item) for item in source_keys)
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(benchmark_path):
        source_key = str(row.get("source_key") or "")
        if source_key in selected:
            rows[source_key].append(dict(row))
    missing = selected - set(rows)
    if missing:
        sample = sorted(missing)[:5]
        raise RuntimeError(
            f"Candidate benchmark misses {len(missing)} selected sources: {sample}"
        )
    return dict(rows)


def _stage_plan(
    *,
    protocol: str,
    dataset: str,
    source_keys: Sequence[str],
    inventory_sha256: str,
    attack_config_sha256: str,
    semantic_metadata: dict[str, Any],
    code_commit: str,
    runtime_tree_hash: str,
) -> dict[str, Any]:
    identity = {
        "protocol": protocol,
        "dataset": dataset,
        "source_keys_sha256": sha256_obj(list(source_keys)),
        "source_count": len(source_keys),
        "inventory_sha256": inventory_sha256,
        "attack_config_sha256": attack_config_sha256,
        "entity_policy_version": ENTITY_TYPE_POLICY_VERSION,
        "entity_policy_sha256": ENTITY_TYPE_POLICY_SHA256,
        "formal_evidence_scope_version": FORMAL_EVIDENCE_SCOPE_VERSION,
        "formal_evidence_scope_sha256": FORMAL_EVIDENCE_SCOPE_SHA256,
        "extractor_version": EXTRACTOR_VERSION,
        "claim_validator_version": VALIDATOR_VERSION,
        "code_commit": code_commit,
        "runtime_tree_sha256": runtime_tree_hash,
        "semantic_protocol": semantic_metadata.get("protocol"),
        "semantic_schema_sha256": semantic_metadata.get("schema_sha256"),
        "semantic_thresholds_sha256": semantic_metadata.get("thresholds_sha256"),
        "minimum_valid_claims": 3,
        "minimum_stealth_pairs": 3,
    }
    return {**identity, "scan_plan_sha256": sha256_obj(identity)}


def _write_or_validate_plan(path: Path, expected: dict[str, Any], resume: bool) -> None:
    if path.exists():
        actual = read_json(path)
        if actual != expected:
            raise RuntimeError(f"Stage plan identity drift: {path}")
        if not resume:
            raise RuntimeError(f"Stage already exists; pass --resume: {path}")
        return
    write_json(expected, path)


def _checkpoint_identity(payload: dict[str, Any]) -> str:
    return sha256_obj(
        {
            key: value
            for key, value in payload.items()
            if key not in {"created_at", "checkpoint_identity_sha256"}
        }
    )


def _load_stage_checkpoint(
    path: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    if not path.is_file():
        return {
            "protocol": plan["protocol"],
            "scan_plan_sha256": plan["scan_plan_sha256"],
            "dataset": plan["dataset"],
            "completed_waves": [],
            "fact_replay": [],
        }
    payload = read_json(path)
    if (
        payload.get("protocol") != plan["protocol"]
        or payload.get("scan_plan_sha256") != plan["scan_plan_sha256"]
        or _checkpoint_identity(payload) != payload.get("checkpoint_identity_sha256")
    ):
        raise RuntimeError("Stage checkpoint identity drift")
    for record in payload.get("completed_waves") or []:
        validate_completed_wave(record, plan)
    for record in payload.get("fact_replay") or []:
        manifest_path = Path(record["manifest_path"])
        if sha256_file(manifest_path) != record["manifest_sha256"]:
            raise RuntimeError(f"Fact replay manifest drift: {manifest_path}")
    return payload


def _write_stage_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    from datetime import datetime, timezone

    row = dict(payload)
    row["created_at"] = datetime.now(timezone.utc).isoformat()
    row["checkpoint_identity_sha256"] = _checkpoint_identity(row)
    write_json(row, path)


def _run_stage(args: argparse.Namespace, stage: str) -> dict[str, Any]:
    inventory_path = Path(args.inventory).resolve()
    inventory = validate_historical_inventory(inventory_path)
    dataset_row = inventory["datasets"][args.dataset]
    attack_path = Path(args.attack_config).resolve()
    attack_config = _load_attack_config(attack_path)

    if stage == "replay":
        source_keys = [str(item) for item in dataset_row["scanned_source_keys"]]
        wave_specs = [
            {
                "wave_index": int(row["wave_index"]),
                "source_start": int(row["source_start"]),
                "source_end": int(row["source_end"]),
                "source_keys": [str(item) for item in row["source_keys"]],
                "old_outputs": row["outputs"],
            }
            for row in dataset_row["completed_waves"]
        ]
        stage_root = (
            Path(args.workspace).resolve() / "replay" / args.dataset
        )
        protocol = HISTORICAL_REPLAY_PROTOCOL
    else:
        pilot_plan = validate_pilot_plan(args.pilot_plan)
        source_keys = [
            str(item)
            for item in pilot_plan["cohorts"][args.cohort][args.dataset]
        ]
        wave_specs = []
        for wave_index, start in enumerate(range(0, len(source_keys), 250)):
            wave_specs.append(
                {
                    "wave_index": wave_index,
                    "source_start": start,
                    "source_end": min(len(source_keys), start + 250),
                    "source_keys": source_keys[start : start + 250],
                }
            )
        stage_root = (
            Path(args.workspace).resolve()
            / "pilots"
            / f"cohort_{args.cohort}"
            / args.dataset
        )
        protocol = PILOT_PROTOCOL
    ensure_dir(stage_root)

    semantic_config = dict(
        (attack_config.get("fact_extraction") or {}).get("semantic_resolver") or {}
    )
    runtime = load_semantic_entity_resolver(
        semantic_config,
        dataset=args.dataset,
        workspace_root=PROJECT_ROOT,
    )
    semantic_metadata = runtime[1].to_dict()
    plan = _stage_plan(
        protocol=protocol,
        dataset=args.dataset,
        source_keys=source_keys,
        inventory_sha256=sha256_file(inventory_path),
        attack_config_sha256=sha256_file(attack_path),
        semantic_metadata=semantic_metadata,
        code_commit=_code_commit(),
        runtime_tree_hash=runtime_tree_sha256(PROJECT_ROOT),
    )
    plan_path = stage_root / "stage_plan.json"
    _write_or_validate_plan(plan_path, plan, args.resume)
    checkpoint_path = stage_root / "stage_checkpoint.json"
    checkpoint = _load_stage_checkpoint(checkpoint_path, plan)
    completed = len(checkpoint["completed_waves"])
    if len(checkpoint.get("fact_replay") or []) not in {0, completed}:
        raise RuntimeError("Fact/source replay checkpoint boundaries diverged")

    source_corpus_path = (
        dataset_row["candidate_benchmark_path"]
        if stage == "replay"
        else pilot_plan["candidate_benchmarks"][args.dataset]["path"]
    )
    candidates = _selected_candidates(source_corpus_path, source_keys)
    max_new = args.max_new_waves
    if max_new is not None and max_new < 1:
        raise ValueError("--max-new-waves must be positive")
    newly_completed = 0
    source_output = ensure_dir(stage_root / "source_replay")
    fact_replay_records = list(checkpoint.get("fact_replay") or [])
    completed_records = list(checkpoint["completed_waves"])

    for spec in wave_specs[completed:]:
        if max_new is not None and newly_completed >= max_new:
            break
        keys = spec["source_keys"]
        if stage == "replay":
            old_facts = Path(spec["old_outputs"]["facts"]["path"])
            old_benchmark = Path(spec["old_outputs"]["benchmark"]["path"])
            fact_replay_dir = ensure_dir(
                stage_root / "fact_replay" / f"wave_{spec['wave_index']:04d}"
            )
            fact_claims_path = fact_replay_dir / f"{args.dataset}_claims.jsonl"
            fact_manifest = generate_paired_claims_file(
                facts_path=old_facts,
                output_path=fact_claims_path,
                benchmark_path=old_benchmark,
                source_corpus_path=dataset_row["candidate_benchmark_path"],
                perturbation_levels=["light"],
                max_pairs_per_fact=1,
                semantic_resolver_config=semantic_config,
                semantic_resolver_runtime=runtime,
                source_key_allowlist=set(keys),
                dataset=args.dataset,
                resume=True,
                force=False,
            )
            fact_manifest_path = fact_claims_path.with_suffix(".manifest.json")
            fact_replay_records.append(
                {
                    "wave_index": spec["wave_index"],
                    "claims_path": str(fact_claims_path.resolve()),
                    "claims_sha256": sha256_file(fact_claims_path),
                    "manifest_path": str(fact_manifest_path.resolve()),
                    "manifest_sha256": sha256_file(fact_manifest_path),
                    "pairs": int(fact_manifest.get("pairs", 0)),
                }
            )

        record = run_pipeline_wave(
            wave_index=int(spec["wave_index"]),
            wave_source_keys=list(keys),
            source_start=int(spec["source_start"]),
            source_end=int(spec["source_end"]),
            candidates_by_source=candidates,
            dataset=args.dataset,
            processed_path=Path(source_corpus_path),
            output_dir=source_output,
            attack_config=attack_config,
            plan=plan,
            semantic_resolver_runtime=runtime,
        )
        completed_records.append(record)
        checkpoint = {
            "protocol": plan["protocol"],
            "scan_plan_sha256": plan["scan_plan_sha256"],
            "dataset": args.dataset,
            "completed_waves": completed_records,
            "fact_replay": fact_replay_records,
        }
        _write_stage_checkpoint(checkpoint_path, checkpoint)
        newly_completed += 1

    if len(completed_records) != len(wave_specs):
        result = {
            "status": "paused",
            "dataset": args.dataset,
            "stage": stage,
            "completed_waves": len(completed_records),
            "total_waves": len(wave_specs),
            "checkpoint": str(checkpoint_path),
        }
        print(json.dumps(result, ensure_ascii=False))
        return result

    eligible: list[str] = []
    fact_paths: list[str] = []
    claim_paths: list[str] = []
    for record in completed_records:
        manifest = validate_completed_wave(record, plan)
        eligible.extend(str(item) for item in manifest["eligible_source_keys"])
        fact_paths.append(str(manifest["outputs"]["facts"]["path"]))
        claim_paths.append(str(manifest["outputs"]["claims"]["path"]))
    report = build_dataset_report(
        dataset=args.dataset,
        stage=stage,
        source_keys=source_keys,
        eligible_source_keys=eligible,
        fact_paths=fact_paths,
        claim_paths=claim_paths,
        old_eligible_rate=(
            float(dataset_row["old_eligible_rate"]) if stage == "replay" else None
        ),
    )
    report.update(
        {
            "stage_plan_path": str(plan_path.resolve()),
            "stage_plan_sha256": sha256_file(plan_path),
            "stage_checkpoint_path": str(checkpoint_path.resolve()),
            "stage_checkpoint_sha256": sha256_file(checkpoint_path),
            "fact_paths": fact_paths,
            "claim_paths": claim_paths,
            "fact_replay": fact_replay_records,
            "pilot_cohort": getattr(args, "cohort", None),
        }
    )
    report["report_identity_sha256"] = sha256_obj(
        {key: value for key, value in report.items() if key != "created_at"}
    )
    report_path = stage_root / f"{stage}_report.json"
    write_json(report, report_path)
    result = {
        "status": report["status"],
        "dataset": args.dataset,
        "stage": stage,
        "report": str(report_path),
        "eligible_sources": report["source_gate"]["eligible_sources"],
        "eligible_rate": report["source_gate"]["eligible_rate"],
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def main() -> int:
    args = parse_args()
    if args.command == "inventory":
        result = build_historical_inventory(PROJECT_ROOT, args.output)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "output": str(Path(args.output).resolve()),
                    "scanned_sources": {
                        dataset: row["scanned_source_count"]
                        for dataset, row in result["datasets"].items()
                    },
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "freeze-pilots":
        result = freeze_pilot_cohorts(args.inventory, args.output)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "output": str(Path(args.output).resolve()),
                    "cohort_hashes": result["cohort_hashes"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.command in {"replay", "pilot"}:
        result = _run_stage(args, args.command)
        return 0 if result["status"] in {"paused", "passed"} else 2
    if args.command == "prepare-audit":
        accepted_claims = list(args.accepted_claims)
        for report_path in args.report:
            report = validate_dataset_report(report_path)
            validate_audit_report_role(report)
            accepted_claims.extend(report.get("claim_paths") or [])
        if not accepted_claims:
            raise RuntimeError(
                "prepare-audit needs --report or --accepted-claims"
            )
        result = prepare_blinded_audit(
            accepted_claims,
            args.hard_negatives,
            args.output_dir,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "finalize":
        audit_report = evaluate_audit(
            args.audit_manifest,
            args.assistant_labels,
            args.user_review,
        )
        audit_report_path = Path(args.output).resolve().parent / "audit_report.json"
        write_json(audit_report, audit_report_path)
        result = freeze_release_gate(
            args.output,
            inventory_path=args.inventory,
            replay_report_paths=args.replay_report,
            pilot_report_paths=args.pilot_report,
            audit_report=audit_report,
            code_commit=_code_commit(),
            runtime_tree_sha256=runtime_tree_sha256(PROJECT_ROOT),
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "passed" else 2
    if args.command == "check-release":
        result = validate_release_gate(
            args.release_gate,
            project_root=PROJECT_ROOT,
            require_current_runtime=True,
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "release_gate_identity_sha256": result[
                        "release_gate_identity_sha256"
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "promote-enron-capacity":
        result = build_enron_capacity_promotion(
            args.release_gate,
            args.output,
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "output": str(Path(args.output).resolve()),
                    "selected_source_count": len(
                        result["selected_source_keys"]
                    ),
                    "promotion_identity_sha256": result[
                        "promotion_identity_sha256"
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "check-enron-promotion":
        result = validate_enron_capacity_promotion(args.promotion)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "promotion_identity_sha256": result[
                        "promotion_identity_sha256"
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
