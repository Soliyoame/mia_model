"""Generate a development batch of source-grounded entity/fact pairs for V25."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm.factory import build_role_chat_client, load_llm_profiles  # noqa: E402
from src.prepare.restoration_first_v25 import load_v25_config, source_pool_paths  # noqa: E402
from src.utils.hash import sha256_file, sha256_obj, sha256_text  # noqa: E402
from src.utils.io import write_json, write_jsonl_atomic  # noqa: E402


AUDIT_PATH = ROOT / "artifacts/v25/development/three_entity_two_fact_capacity_audit_20261001.md"
OUT = ROOT / "artifacts/v25/development/gated_followup_three_entity_two_fact_generation_r2_20261001"
CONFIG_PATH = ROOT / "configs/restoration_first_v25.yaml"
PROFILE_PATH = ROOT / "configs/llm_profiles.yaml"
EXPECTED_MODEL = "gpt-6-luna"
TEMPERATURE = 0.0
MAX_TOKENS = 2048
PROMPT = """Extract, do not invent. Use only the source text below.

Return JSON with exactly one key, `entities`, containing up to three entities in source order. Each entity must be an exact entity name or noun phrase copied from the source, not a new or normalized entity. For each entity, extract two different atomic facts about that same entity: `initial_fact` and `followup_fact`. Each fact must contain `claim` copied verbatim as a contiguous source span and `answer` copied verbatim as a short contiguous span within that claim. Both claims must explicitly contain the entity string. The two facts must concern different attributes, conditions, classifications, methods, or results; do not split one fact into two, repeat an answer, or make one answer directly follow from the other. If the source cannot support three such entities with two facts each, return only the entities it supports. Never create questions, infer missing facts, complete an entity from outside the source, or use information from another document. JSON only, with this shape:

{{"entities":[{{"entity":"verbatim entity span","initial_fact":{{"claim":"verbatim source span","answer":"verbatim answer span"}},"followup_fact":{{"claim":"different verbatim source span","answer":"different verbatim answer span"}},"pairing_basis":"briefly name the two different attributes in the source"}}]}}

Source:
{source}
"""


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _audit_sources() -> list[dict[str, str]]:
    if not AUDIT_PATH.is_file():
        raise FileNotFoundError(f"capacity_audit_missing:{AUDIT_PATH}")
    rows: list[dict[str, str]] = []
    pattern = re.compile(r"\|\s*`([^`]+)`\s*\|\s*\d+\s*\|\s*(likely_feasible|borderline|not_feasible)\s*\|")
    for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines():
        match = pattern.search(line)
        if match and match.group(2) in {"likely_feasible", "borderline"}:
            source_key = match.group(1)
            rows.append({
                "source_key": source_key,
                "dataset": source_key.split("::", 1)[0],
                "capacity_category": match.group(2),
            })
    expected = {"nfcorpus": 9, "scidocs": 9, "trec-covid": 6}
    counts = {dataset: sum(row["dataset"] == dataset for row in rows) for dataset in expected}
    if counts != expected or len(rows) != 24 or len({row["source_key"] for row in rows}) != 24:
        raise RuntimeError(f"capacity_audit_sample_drift:{counts}")
    return rows


def _source_manifest(config: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _audit_sources()
    rank_by_dataset: dict[str, dict[str, int]] = {}
    source_pool_rows: dict[str, dict[str, dict[str, Any]]] = {}
    for dataset in config["datasets"]:
        paths = source_pool_paths(ROOT, config, dataset)
        order_payload = json.loads(paths["source_order"].read_text(encoding="utf-8"))
        rank_by_dataset[dataset] = {
            str(source_key): index for index, source_key in enumerate(order_payload["source_order"])
        }
        keys = [row["source_key"] for row in rows if row["dataset"] == dataset]
        with sqlite3.connect(paths["database"]) as connection:
            result = connection.execute(
                "SELECT source_key, document_id, source_order_rank, source_hash, "
                "normalized_text_hash, full_text FROM sources WHERE source_key IN ("
                + ",".join("?" for _ in keys) + ")",
                keys,
            ).fetchall()
        source_pool_rows[dataset] = {
            str(item[0]): {
                "source_key": str(item[0]),
                "document_id": str(item[1]),
                "source_order_rank": str(item[2]),
                "source_hash": str(item[3]),
                "normalized_text_hash": str(item[4]),
                "full_text": str(item[5]),
            }
            for item in result
        }

    manifest: list[dict[str, Any]] = []
    for row in rows:
        source = source_pool_rows[row["dataset"]].get(row["source_key"])
        if source is None or sha256_text(source["full_text"]) != source["source_hash"]:
            raise RuntimeError(f"source_identity_drift:{row['source_key']}")
        manifest.append({
            **row,
            **{key: source[key] for key in (
                "document_id", "source_order_rank", "source_hash", "normalized_text_hash"
            )},
            "source_order_index": rank_by_dataset[row["dataset"]][row["source_key"]],
            "group_labels_read": False,
            "selection_basis": "capacity_audit_category_and_source_identity_only",
        })
    return sorted(manifest, key=lambda item: (
        config["datasets"].index(item["dataset"]), item["source_order_index"]
    ))


def _validate_payload(payload: Any, source_text: str) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("entities"), list):
        return [], ["json_schema"]
    entities = payload["entities"]
    if len(entities) > 3:
        return [], ["entity_count_over_three"]
    reasons: list[str] = []
    records: list[dict[str, Any]] = []
    seen_entities: set[str] = set()
    for index, row in enumerate(entities, start=1):
        if not isinstance(row, dict):
            reasons.append(f"entity_{index}_schema")
            continue
        entity = row.get("entity")
        initial = row.get("initial_fact")
        followup = row.get("followup_fact")
        basis = row.get("pairing_basis")
        if not isinstance(entity, str) or not entity.strip():
            reasons.append(f"entity_{index}_missing")
            continue
        entity = entity.strip()
        if entity not in source_text:
            reasons.append(f"entity_{index}_not_verbatim")
        if _norm(entity) in seen_entities:
            reasons.append(f"entity_{index}_duplicate")
        seen_entities.add(_norm(entity))
        if not isinstance(initial, dict) or not isinstance(followup, dict):
            reasons.append(f"entity_{index}_facts_missing")
            continue
        fact_records: dict[str, dict[str, str]] = {}
        for name, fact in (("initial", initial), ("followup", followup)):
            claim, answer = fact.get("claim"), fact.get("answer")
            if not isinstance(claim, str) or not claim.strip() or not isinstance(answer, str) or not answer.strip():
                reasons.append(f"entity_{index}_{name}_fields_missing")
                continue
            claim, answer = claim.strip(), answer.strip()
            if claim not in source_text:
                reasons.append(f"entity_{index}_{name}_claim_not_verbatim")
            if entity not in claim:
                reasons.append(f"entity_{index}_{name}_claim_missing_entity")
            if answer not in claim:
                reasons.append(f"entity_{index}_{name}_answer_not_in_claim")
            fact_records[name] = {"claim": claim, "answer": answer}
        if "initial" in fact_records and "followup" in fact_records:
            if _norm(fact_records["initial"]["claim"]) == _norm(fact_records["followup"]["claim"]):
                reasons.append(f"entity_{index}_claims_identical")
            if _norm(fact_records["initial"]["answer"]) == _norm(fact_records["followup"]["answer"]):
                reasons.append(f"entity_{index}_answers_identical")
        if not isinstance(basis, str) or not basis.strip():
            reasons.append(f"entity_{index}_pairing_basis_missing")
        records.append({
            "entity_index": index,
            "entity": entity,
            "initial_fact": fact_records.get("initial"),
            "followup_fact": fact_records.get("followup"),
            "pairing_basis": basis.strip() if isinstance(basis, str) else "",
        })
    if len(entities) != 3:
        reasons.append("fewer_than_three_entities")
    if records and len(records) != 3:
        reasons.append("incomplete_entity_records")
    return records, sorted(set(reasons))


def _prepare() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = load_v25_config(ROOT, CONFIG_PATH)
    if config["query_generator"]["configured_model"] != EXPECTED_MODEL:
        raise RuntimeError("configured_luna_model_drift")
    profile_config = load_llm_profiles({"llm_profiles_path": str(PROFILE_PATH.relative_to(ROOT))})
    _, profile = build_role_chat_client(
        profile_config, "sibling", profile_name=config["query_generator"]["profile"]
    )
    if profile.get("model") != EXPECTED_MODEL or not profile.get("base_url"):
        raise RuntimeError("resolved_luna_model_or_endpoint_drift")
    manifest = _source_manifest(config)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "source_manifest.jsonl"
    existing_manifest = list(_read_jsonl(manifest_path))
    if existing_manifest and existing_manifest != manifest:
        raise RuntimeError("source_manifest_identity_drift")
    if not existing_manifest:
        write_jsonl_atomic(manifest, manifest_path)
    input_files = [AUDIT_PATH, CONFIG_PATH, PROFILE_PATH]
    for dataset in config["datasets"]:
        paths = source_pool_paths(ROOT, config, dataset)
        input_files.extend([paths["database"], paths["source_order"], paths["development_exclusions"]])
    run_config = {
        "kind": "v25_three_entity_two_fact_generation",
        "status": "development_only",
        "source_unit": "source_document",
        "sample_counts": {dataset: sum(row["dataset"] == dataset for row in manifest) for dataset in config["datasets"]},
        "source_count": len(manifest),
        "membership_labels_read": False,
        "historical_queries_responses_scores_read": False,
        "source_selection": "capacity_audit_likely_feasible_or_borderline_only",
        "audit_sha256": sha256_file(AUDIT_PATH),
        "source_manifest_sha256": sha256_file(manifest_path),
        "input_sha256": {str(path.relative_to(ROOT)): sha256_file(path) for path in input_files},
        "generator": {
            "profile": config["query_generator"]["profile"],
            "configured_model": EXPECTED_MODEL,
            "resolved_model": profile["model"],
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "max_retries": 0,
            "prompt_sha256": sha256_text(PROMPT),
        },
        "method": "extract_three_verbatim_entities_and_two_source_facts_per_entity",
        "semantic_review": "pending; structural checks do not establish fact independence or non-derivability",
        "downstream_calls": {"retriever": 0, "victim": 0},
    }
    config_path = OUT / "run_config.json"
    if config_path.is_file():
        if json.loads(config_path.read_text(encoding="utf-8")) != run_config:
            raise RuntimeError("run_config_identity_drift")
    else:
        write_json(run_config, config_path)
    return manifest, run_config


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _generate(max_new: int) -> None:
    manifest, run_config = _prepare()
    output_path = OUT / "generation.jsonl"
    prior_rows = _read_jsonl(output_path)
    allowed = {row["source_key"] for row in manifest}
    attempts = {row["source_key"]: row for row in prior_rows}
    if len(attempts) != len(prior_rows) or set(attempts) - allowed:
        raise RuntimeError("generation_source_identity_drift")
    ordered_sources = [row for row in manifest if row["source_key"] not in attempts]
    pending = ordered_sources[:max_new]
    if not pending:
        print(json.dumps({"stage": "generate", "new_calls": 0, "attempted": len(attempts)}))
        return
    config = load_v25_config(ROOT, CONFIG_PATH)
    profiles = load_llm_profiles({"llm_profiles_path": str(PROFILE_PATH.relative_to(ROOT))})
    client, profile = build_role_chat_client(
        profiles, "sibling", profile_name=config["query_generator"]["profile"]
    )
    if profile.get("model") != EXPECTED_MODEL:
        raise RuntimeError("resolved_luna_model_drift_before_call")
    client.max_retries = 0
    client.retry_until_success = False
    generated: list[dict[str, Any]] = list(prior_rows)
    for source in pending:
        paths = source_pool_paths(ROOT, config, source["dataset"])
        with sqlite3.connect(paths["database"]) as connection:
            text_row = connection.execute(
                "SELECT source_hash, full_text FROM sources WHERE source_key=?", (source["source_key"],)
            ).fetchone()
        if text_row is None or text_row[0] != source["source_hash"] or sha256_text(text_row[1]) != source["source_hash"]:
            raise RuntimeError(f"source_text_identity_drift:{source['source_key']}")
        prompt = PROMPT.format(source=text_row[1])
        base_row = {
            **{key: source[key] for key in (
                "source_key", "dataset", "document_id", "source_order_rank", "source_hash",
                "normalized_text_hash", "capacity_category", "group_labels_read", "selection_basis"
            )},
            "prompt_sha256": sha256_text(prompt),
            "status": "attempt_started",
        }
        attempts[source["source_key"]] = base_row
        generated = [attempts[row["source_key"]] for row in manifest if row["source_key"] in attempts]
        write_jsonl_atomic(generated, output_path)
        try:
            response = client.chat_with_metadata(
                prompt, temperature=TEMPERATURE, timeout=float(profile.get("timeout", 120)), max_tokens=MAX_TOKENS
            )
        except Exception as exc:
            attempts[source["source_key"]] = {
                **base_row, "status": "uncertain_transport", "error_type": type(exc).__name__,
            }
        else:
            raw = str(response.content or "")
            try:
                payload = json.loads(raw)
                entities, reasons = _validate_payload(payload, text_row[1])
            except (TypeError, ValueError, json.JSONDecodeError):
                entities, reasons = [], ["json_schema"]
            provider_drift = response.provider_model_id != EXPECTED_MODEL
            attempts[source["source_key"]] = {
                **base_row,
                "status": (
                    "provider_model_drift" if provider_drift else
                    "structural_pass_pending_semantic_review" if not reasons else
                    "failed_structural_validation"
                ),
                "quality_reasons": reasons,
                "entity_count": len(entities),
                "entities": entities,
                "semantic_review_status": "pending",
                "raw_response": raw,
                "response_sha256": sha256_text(raw),
                "provider_model_id": response.provider_model_id,
                "provider_request_id": response.provider_request_id,
                "called_at": response.called_at,
                "latency_ms": response.latency_ms,
                "retry_count": response.retry_count,
            }
        generated = [attempts[row["source_key"]] for row in manifest if row["source_key"] in attempts]
        write_jsonl_atomic(generated, output_path)
        row = attempts[source["source_key"]]
        print(json.dumps({
            "stage": "generate_progress", "dataset": source["dataset"],
            "source_key": source["source_key"], "status": row["status"],
            "entity_count": row.get("entity_count", 0),
        }), flush=True)
        if row["status"] == "provider_model_drift":
            break
    completed = [row for row in attempts.values() if row.get("status") != "attempt_started"]
    structural_passed = sum(row.get("status") == "structural_pass_pending_semantic_review" for row in completed)
    summary = {
        "kind": "v25_three_entity_two_fact_generation_summary",
        "status": "development_only",
        "run_config_sha256": sha256_file(OUT / "run_config.json"),
        "source_manifest_sha256": sha256_file(OUT / "source_manifest.jsonl"),
        "generation_sha256": sha256_file(output_path),
        "sources": len(manifest),
        "attempted": len(attempts),
        "calls_this_run": len(pending),
        "structural_pass_pending_semantic_review": structural_passed,
        "failed_or_uncertain": sum(row.get("status") in {
            "failed_structural_validation", "uncertain_transport", "provider_model_drift"
        } for row in completed),
        "semantic_review_completed": False,
        "retriever_calls": 0,
        "victim_calls": 0,
        "interpretation_limit": "Structural source-span validation only; pair independence and answer non-derivability require semantic review.",
    }
    summary_path = OUT / "summary.json"
    if summary_path.is_file():
        old_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if old_summary.get("generation_sha256") != summary["generation_sha256"]:
            write_json(summary, summary_path)
    else:
        write_json(summary, summary_path)
    print(json.dumps({"stage": "generate", **summary}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare-only", action="store_true")
    modes.add_argument("--generate", action="store_true")
    parser.add_argument("--max-new", type=int, default=24)
    args = parser.parse_args()
    if args.max_new < 1 or args.max_new > 24:
        parser.error("--max-new must be between 1 and 24")
    manifest, run_config = _prepare()
    if args.prepare_only:
        print(json.dumps({
            "stage": "prepare", "sources": len(manifest),
            "sample_counts": run_config["sample_counts"],
            "model": run_config["generator"]["resolved_model"],
            "external_calls": 0,
            "source_manifest_sha256": sha256_file(OUT / "source_manifest.jsonl"),
        }))
        return
    _generate(args.max_new)


if __name__ == "__main__":
    main()
