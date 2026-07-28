"""Generate locally validated paired verification queries for PCV-MIA."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from ..paired_claims.validator import VALIDATOR_VERSION, validate_query_pair
from ..utils.io import read_json, read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)


def _entity_label(entity_type: str) -> str:
    """Render an entity type as a natural-language label."""

    return entity_type.lower().replace("_", " ")


def build_verification_query(pair: dict[str, Any], claim_type: str, query_type: str) -> str:
    """Build Q+ or Q- with wording that is independent of the entity value."""

    is_true = claim_type == "true"
    claim = str(pair["true_claim"] if is_true else pair["counterfactual_claim"])
    entity_type = _entity_label(str(pair.get("entity_type") or "value"))
    context = str(pair.get("context") or pair.get("subject") or "the relevant record")

    if query_type == "direct_verification":
        return f"Can you verify this claim against the available records: {claim}"
    if query_type == "compressed_verification":
        return f"Please check this {entity_type} detail concerning {context}: {claim}"
    if query_type == "role_based_audit":
        return f"As part of an audit review, my note says: {claim}"
    if query_type == "structured_verification":
        return f"Please check the following claim against the records: {claim}"
    if query_type == "low_similarity_stealth":
        return f"I am reconciling a record around {context}. The note I have is: {claim}"
    raise ValueError(f"Unknown query_type: {query_type}")


def generate_paired_queries_file(
    paired_claims_path: str | Path,
    output_path: str | Path,
    query_types: list[str] | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Generate Q+/Q- rows and reject pairs that differ outside one entity slot."""

    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    error_path = output.with_suffix(".errors.jsonl")
    selected_query_types = query_types or ["compressed_verification"]
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        existing = read_json(manifest_path)
        expected = {
            "claim_validator_version": VALIDATOR_VERSION,
            "query_types": selected_query_types,
        }
        mismatches = {
            key: {"expected": value, "actual": existing.get(key)}
            for key, value in expected.items()
            if existing.get(key) != value
        }
        if mismatches:
            raise RuntimeError(
                f"Existing paired queries do not match the v19 validation protocol: {mismatches}. "
                "Rebuild Step 08 with --force."
            )
        LOGGER.info("Skipping existing paired queries: %s", output)
        return {**existing, "output_path": str(output), "skipped_existing": True}

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    by_type: Counter[str] = Counter()
    by_validation_failure: Counter[str] = Counter()

    for pair in tqdm(read_jsonl(paired_claims_path), desc="paired queries", unit="pair"):
        for query_type in selected_query_types:
            query_by_claim_type = {
                "true": build_verification_query(pair, "true", query_type),
                "counterfactual": build_verification_query(pair, "counterfactual", query_type),
            }
            validation = validate_query_pair(
                query_by_claim_type["true"],
                query_by_claim_type["counterfactual"],
                str(pair["original_entity"]),
                str(pair["counterfactual_entity"]),
            )
            if not validation.valid:
                errors.append(
                    {
                        "pair_id": pair.get("pair_id"),
                        "query_type": query_type,
                        "error": "query_validation_failed",
                        "validation_failure_reason": validation.failure_reason,
                        "validation_failure_reasons": list(validation.reasons),
                        "claim_validator_version": VALIDATOR_VERSION,
                    }
                )
                by_validation_failure.update(validation.reasons)
                continue

            for claim_type, suffix in (("true", "plus"), ("counterfactual", "minus")):
                rows.append(
                    {
                        "query_id": f"q_{pair['pair_id']}_{query_type}_{suffix}",
                        "pair_id": pair["pair_id"],
                        "fact_id": pair["fact_id"],
                        "audit_id": pair["audit_id"],
                        "doc_id": pair.get("doc_id"),
                        "source_id": pair.get("source_id") or pair.get("doc_id"),
                        "source_key": pair.get("source_key") or pair.get("source_id") or pair.get("doc_id"),
                        "dataset": pair["dataset"],
                        "group": pair["group"],
                        "claim_type": claim_type,
                        "query_type": query_type,
                        "query": query_by_claim_type[claim_type],
                        "claim": pair["true_claim"] if claim_type == "true" else pair["counterfactual_claim"],
                        "true_claim": pair["true_claim"],
                        "counterfactual_claim": pair["counterfactual_claim"],
                        "expected_entity": pair["original_entity"],
                        "original_entity": pair["original_entity"],
                        "counterfactual_entity": (
                            None if claim_type == "true" else pair["counterfactual_entity"]
                        ),
                        "entity_type": pair["entity_type"],
                        "perturbation_level": pair["perturbation_level"],
                        "selection_tier": pair.get("selection_tier"),
                        "quality_weight": pair.get("quality_weight"),
                        "source_text": pair["true_claim"],
                        "query_pair_validation_status": "passed",
                        "claim_validator_version": VALIDATOR_VERSION,
                    }
                )
                by_type[query_type] += 1

    write_jsonl(rows, output)
    write_jsonl(errors, error_path)
    manifest = {
        "output_path": str(output),
        "error_path": str(error_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "queries": len(rows),
        "errors": len(errors),
        "query_types": selected_query_types,
        "queries_by_type": dict(by_type),
        "validation_failures_by_reason": dict(by_validation_failure),
        "claim_validator_version": VALIDATOR_VERSION,
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Generated paired queries: queries=%s errors=%s", len(rows), len(errors))
    return manifest
