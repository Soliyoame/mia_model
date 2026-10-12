"""共享 G query 的确定性派生与冻结。"""

from __future__ import annotations

import re
from typing import Any

from src.utils.hash import sha256_obj
from src.utils.hash import sha256_file
from .artifacts import ArtifactStore, read_rows, unique_map, write_once, write_json_atomic
from .config import ExperimentConfig
from .scoring import formatting_answer_aliases
from .types import FactBundle, QueryRecord, SourceRecord

def anchored_question(anchor_claim: str, target_question: str) -> str:
    claim = re.sub(r"\s+", " ", str(anchor_claim or "").strip())
    question = str(target_question or "").strip()
    if not claim or not question:
        return ""
    if claim[-1] not in ".!?":
        claim += "."
    return f"The source reports: “{claim}” {question}"


def build_frozen_queries_for_source(
    source: SourceRecord, records: FactBundle, experiment_id: str,
) -> list[QueryRecord]:
    initial_facts = records["initial_facts"]
    target = records["remote_target"]
    anchored = records["anchored_followups"]
    remote_only = records["no_anchor_followups"]
    if not (len(initial_facts) == len(anchored) == len(remote_only) == 3):
        raise RuntimeError("shared_g_slot_count_drift")

    queries: list[QueryRecord] = []
    for arm, facts in (("initial", initial_facts), ("correct_anchor", anchored), ("remote_only", remote_only)):
        for index, fact in enumerate(facts):
            if arm == "correct_anchor":
                if (fact.get("anchor") != initial_facts[index]["answer"]
                        or fact.get("anchor_claim") != initial_facts[index]["claim"]
                        or fact["question"] != anchored_question(
                            initial_facts[index]["claim"], target["question"],
                        )):
                    raise RuntimeError("anchored_query_derivation_drift")
            elif arm == "remote_only" and fact["question"] != target["question"]:
                raise RuntimeError("shared_g_question_drift")
            answer_record = fact if arm == "initial" else target
            queries.append({
                "query_id": sha256_obj({
                    "experiment": experiment_id,
                    "source_hash": source["source_hash"],
                    "arm": arm,
                    "slot": index,
                }),
                "source_key": source["source_key"],
                "dataset": source["dataset"],
                "arm": arm,
                "slot_index": index,
                "question": fact["question"],
                "retrieval_query": fact["question"],
                "answer": answer_record["answer"],
                "answer_aliases": formatting_answer_aliases(answer_record["answer"]),
                "claim": answer_record["claim"],
                "anchor": fact.get("anchor"),
                "anchor_claim": fact.get("anchor_claim"),
                "region_diagnostics": records["region_diagnostics"],
            })
    if len({row["query_id"] for row in queries}) != 9:
        raise RuntimeError("frozen_query_id_drift")
    return queries


def freeze(config: ExperimentConfig, store: ArtifactStore) -> dict[str, Any]:
    # 局部导入避免构造器与 query 派生器互相初始化。
    from .construction import (generation_records, qualification_progress, review_decisions,
                               validate_candidate_generations, validate_construction, _parse_json_with_diagnostics)
    from .sources import read_source_text, select_qualified_sources

    run = store.validate()
    if run.get("frozen_artifacts"):
        store.validate(frozen=True)
        return {"stage": "freeze", "status": "already_frozen"}
    if any(store.path(name, dataset).exists() for dataset in config.datasets
           for name in ("retrieval.jsonl", "initial_responses.jsonl", "followup_responses.jsonl")):
        raise RuntimeError("freeze_after_formal_execution_forbidden")
    candidates = read_rows(store.path("candidate_manifest.jsonl"))
    generations = generation_records(store)
    validate_candidate_generations(candidates, generations, run["model_profiles"]["sibling"])
    if any(row["status"] == "failed_quality_gate" and row["attempt"] < 2 for row in generations.values()):
        raise RuntimeError("construction_repair_pending")
    passed = {key for key, row in generations.items() if row["status"] == "passed"}
    decisions = review_decisions(store, generations)
    if set(decisions) != passed:
        raise RuntimeError("semantic_review_coverage_incomplete")
    accepted = {key for key, decision in decisions.items() if decision["accepted"]}
    rejected = set(decisions) - accepted
    sources = select_qualified_sources(config, candidates, accepted)
    indices = [source for source in sources if source["group"] == "KB_Member"]
    queries: list[dict[str, Any]] = []
    profile = run["model_profiles"]["sibling"]
    for source in sources:
        row = generations[source["source_key"]]
        if row["source_hash"] != source["source_hash"] or row["profile_identity"] != profile:
            raise RuntimeError("generation_source_or_profile_drift")
        payload, _ = _parse_json_with_diagnostics(row["raw_response"])
        replayed, reasons = validate_construction(payload, read_source_text(config, source),
                                                  config.data["construction"]["maximum_answer_words"])
        if reasons or replayed != row["records"]:
            raise RuntimeError("generation_replay_drift")
        queries.extend(build_frozen_queries_for_source(source, replayed, config.data["experiment_id"]))
    unique_map(queries, "query_id")
    if len(queries) != 9 * len(accepted):
        raise RuntimeError("frozen_query_count_drift")
    write_once(store.path("source_manifest.jsonl"), sources)
    write_once(store.path("index_manifest.jsonl"), indices)
    write_once(store.path("query_plan.jsonl"), queries)
    run.update(status="frozen_before_retrieval_and_victim", accepted_source_count=len(accepted),
               source_count=len(sources), index_source_count=len(indices),
               dataset_counts={dataset: sum(source["dataset"] == dataset for source in sources) for dataset in config.datasets},
               code_commit=store.git_commit(),
               construction_failures=len(generations) - len(passed), semantic_rejections=len(rejected),
               qualification=qualification_progress(config, store),
               prior_v24_raw_document_reuse={dataset: sum(source["prior_v24_raw_document_reused"] for source in sources
                                                         if source["dataset"] == dataset) for dataset in config.datasets},
               historical_raw_document_reuse={dataset: sum(source["history_raw_document_reused"] for source in sources
                                                           if source["dataset"] == dataset) for dataset in config.datasets},
               frozen_artifacts={name: sha256_file(store.path(name)) for name in
                                 ("generation.jsonl", "semantic_review.json", "query_plan.jsonl")})
    if store.path("semantic_review_requests.jsonl").exists():
        run["frozen_artifacts"]["semantic_review_requests.jsonl"] = sha256_file(store.path("semantic_review_requests.jsonl"))
    run["artifacts"].update({name: sha256_file(store.path(name)) for name in ("source_manifest.jsonl", "index_manifest.jsonl")})
    write_json_atomic(store.path("run_config.json"), run)
    return {"stage": "freeze", "status": "frozen", "accepted_sources": len(accepted), "queries": len(queries)}
