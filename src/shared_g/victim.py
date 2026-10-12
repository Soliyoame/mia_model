"""真实请求的逐槽门控、响应验证与断点恢复。"""

from __future__ import annotations

import time
import logging
from typing import Any

from src.llm.factory import build_victim_client, llm_profile_identity, load_llm_profiles
from src.llm.response_validation import strict_response_metadata_error
from src.utils.hash import sha256_file, sha256_obj, sha256_text

from .artifacts import ArtifactStore, append_request, read_rows, request_records, unique_map, read_response_adjudications
from .config import ExperimentConfig
from .retrieval import rag_prompt, validate_retrieval
from .scoring import gated_queries, source_scores


def response_records(store: ArtifactStore, dataset: str, followup: bool) -> list[dict[str, Any]]:
    return request_records(store.path("followup_responses.jsonl" if followup else "initial_responses.jsonl", dataset))


def validate_responses(config: ExperimentConfig, store: ArtifactStore, dataset: str,
                       planned: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    queries = unique_map(planned, "query_id")
    observed = unique_map(rows, "query_id")
    if set(observed) - set(queries):
        raise RuntimeError("unexpected_saved_response")
    identity = llm_profile_identity(config.profiles()["victim"])
    retrieval_path = store.path("retrieval.jsonl", dataset)
    if queries and not retrieval_path.is_file():
        raise RuntimeError("retrieval_required_before_victim")
    retrieval_hash = sha256_file(retrieval_path) if queries else None
    retrieval = unique_map(read_rows(retrieval_path), "query_id")
    for key, row in observed.items():
        query = queries[key]
        error = strict_response_metadata_error(row.get("response"), provider_model_id=row.get("provider_model_id"),
            provider_request_id=row.get("provider_request_id"), called_at=row.get("called_at"),
            expected_model_id=identity["model"], configured_model_version=identity["model_version"])
        if row["status"] != "completed" or error:
            raise RuntimeError("unresolved_or_invalid_victim_response_preserved")
        if (row["retrieval_sha256"] != retrieval_hash or row["profile_identity"] != identity
                or row["response_sha256"] != sha256_text(row["response"])
                or row["prompt_sha256"] != retrieval[key]["prompt_sha256"]
                or any(row.get(field) != query[field] for field in ("source_key", "arm", "slot_index"))):
            raise RuntimeError("saved_response_identity_drift")
        if row["record_sha256"] != sha256_obj({k: v for k, v in row.items() if k != "record_sha256"}):
            raise RuntimeError("saved_response_record_drift")


def validate_cell_order(config: ExperimentConfig, store: ArtifactStore, dataset: str) -> None:
    if dataset not in config.datasets:
        raise ValueError("unknown_dataset")
    all_queries = read_rows(store.path("query_plan.jsonl"))
    sources = read_rows(store.path("source_manifest.jsonl"))
    adjudications = read_response_adjudications(store)
    for previous in config.datasets[:config.datasets.index(dataset)]:
        queries = [q for q in all_queries if q["dataset"] == previous]
        if not queries:
            continue
        initial = response_records(store, previous, False)
        followups = response_records(store, previous, True)
        validate_responses(config, store, previous, [q for q in queries if q["arm"] == "initial"], initial)
        expected = gated_queries(queries, initial, matcher=config.data["answer_policy"]["matcher"], adjudications=adjudications)
        validate_responses(config, store, previous, expected, followups)
        source_scores([s for s in sources if s["source_key"] in {q["source_key"] for q in queries}],
                      queries, initial, followups, 1.0, matcher=config.data["answer_policy"]["matcher"], adjudications=adjudications)


def run_victim(config: ExperimentConfig, store: ArtifactStore, dataset: str,
               followup: bool, max_new: int = 200) -> dict[str, Any]:
    store.validate(frozen=True)
    validate_cell_order(config, store, dataset)
    if max_new < 1:
        raise ValueError("positive_wave_budget_required")
    queries = [q for q in read_rows(store.path("query_plan.jsonl")) if q["dataset"] == dataset]
    retrieval = validate_retrieval(config, store, dataset)
    initials = [q for q in queries if q["arm"] == "initial"]
    adjudications = read_response_adjudications(store)
    if followup:
        initial_responses = response_records(store, dataset, False)
        validate_responses(config, store, dataset, initials, initial_responses)
        planned = gated_queries(queries, initial_responses, matcher=config.data["answer_policy"]["matcher"], adjudications=adjudications)
    else:
        planned = initials
    saved_rows = response_records(store, dataset, followup)
    validate_responses(config, store, dataset, planned, saved_rows)
    saved = unique_map(saved_rows, "query_id")
    pending = [q for q in planned if q["query_id"] not in saved][:max_new]
    name = "followup_responses.jsonl" if followup else "initial_responses.jsonl"
    if not pending:
        return {"stage": name.removesuffix("_responses.jsonl"), "dataset": dataset,
                "new_calls": 0, "complete": len(saved) == len(planned)}
    profiles = load_llm_profiles({"llm_profiles_path": str(config.resolve(config.data["runtime"]["llm_profiles_path"]))})
    client, profile = build_victim_client(profiles, profile_name=config.data["runtime"]["victim_profile"])
    identity = llm_profile_identity(profile)
    if identity != llm_profile_identity(config.profiles()["victim"]):
        raise RuntimeError("victim_client_profile_drift")
    fingerprints = {row.get("system_fingerprint") for ds in config.datasets for flag in (False, True)
                    for row in response_records(store, ds, flag) if row.get("provider_model_id")}
    if len(fingerprints) > 1:
        raise RuntimeError("victim_fingerprint_drift")
    policy = config.data["runtime"]["generation"]
    retrieval_hash = sha256_file(store.path("retrieval.jsonl", dataset))
    for completed_count, query in enumerate(pending, start=len(saved) + 1):
        found = retrieval[query["query_id"]]
        context, prompt = rag_prompt(config, query, found["retrieved_chunks"])
        if sha256_text(context) != found["context_sha256"] or sha256_text(prompt) != found["prompt_sha256"]:
            raise RuntimeError("victim_prompt_drift")
        row = {"request_key": query["query_id"], "query_id": query["query_id"], "source_key": query["source_key"],
               "arm": query["arm"], "slot_index": query["slot_index"], "status": "attempt_started",
               "retrieval_sha256": retrieval_hash, "prompt_sha256": sha256_text(prompt), "profile_identity": identity}
        append_request(store.path(name, dataset), row)
        try:
            result = client.generate_with_metadata(prompt, temperature=policy["temperature"],
                                                     timeout=policy["timeout"], max_tokens=policy["max_tokens"])
            error = strict_response_metadata_error(result.content, provider_model_id=result.provider_model_id,
                provider_request_id=result.provider_request_id, called_at=result.called_at,
                expected_model_id=profile["model"], configured_model_version=profile["model_version"])
            valid = not error and result.retry_count == 0 and (not fingerprints or result.system_fingerprint in fingerprints)
            row.update(status="completed" if valid else "invalid_provider_response", response=result.content,
                       response_sha256=sha256_text(result.content), provider_model_id=result.provider_model_id,
                       provider_request_id=result.provider_request_id, system_fingerprint=result.system_fingerprint,
                       called_at=result.called_at, input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                       latency_ms=result.latency_ms, retry_count=result.retry_count)
            if not valid:
                row["validation_code"] = error.split(":", 1)[0] if error else "retry_or_fingerprint_drift"
            fingerprints.add(result.system_fingerprint)
        except Exception as exc:
            row.update(status="uncertain_transport", error_type=type(exc).__name__)
        row["record_sha256"] = sha256_obj(row)
        append_request(store.path(name, dataset), row)
        logging.getLogger(__name__).info("victim dataset=%s phase=%s completed=%d planned=%d status=%s",
                                        dataset, "followup" if followup else "initial", completed_count,
                                        len(planned), row["status"])
        if row["status"] != "completed":
            raise RuntimeError("victim_invalid_response_stop_preserve_evidence")
        time.sleep(policy["request_interval_seconds"])
    return {"stage": name.removesuffix("_responses.jsonl"), "dataset": dataset, "new_calls": len(pending),
            "completed": len(saved) + len(pending), "planned": len(planned), "complete": len(saved) + len(pending) == len(planned)}
