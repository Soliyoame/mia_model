"""Fresh source-level validation of the shared-G point-score successor."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import random
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.metrics import (  # noqa: E402
    bootstrap_auc_ci, bootstrap_macro_auc_ci, clopper_pearson_interval,
    rates_at_threshold, roc_auc, threshold_curve, tpr_at_fpr_details,
)
from src.prepare.restoration_first_v25 import (  # noqa: E402
    load_v25_config, read_source_text, source_pool_input_hashes, source_pool_paths,
)
from src.utils.hash import sha256_file, sha256_obj, sha256_text  # noqa: E402
from src.utils.io import load_yaml, read_jsonl, write_json, write_jsonl_atomic  # noqa: E402

PILOT_PATH = ROOT / "scripts/95_run_v25_shared_g_pilot.py"
SPEC = importlib.util.spec_from_file_location("v25_shared_g_successor_pilot", PILOT_PATH)
assert SPEC is not None and SPEC.loader is not None
PILOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PILOT)
DEFAULT_CONFIG = ROOT / "configs/v25_shared_g_query_stability.yaml"
ARMS = ("correct_anchor", "remote_only")


def read_rows(path: Path) -> list[dict[str, Any]]:
    return list(read_jsonl(path)) if path.is_file() else []


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def identity_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        result = {str(value["source_key"])} if value.get("source_key") else set()
        for child in value.values():
            result.update(identity_keys(child))
        return result
    if isinstance(value, list):
        return set().union(*(identity_keys(child) for child in value))
    return set()


def select_blind_sources(
    pool: list[dict[str, Any]], count: int, seed: int, minimum_words: int,
    excluded_keys: set[str], excluded_hashes: set[str],
) -> list[dict[str, Any]]:
    candidates = [row for row in pool if row["source_key"] not in excluded_keys
                  and row["source_hash"] not in excluded_hashes
                  and row["normalized_text_hash"] not in excluded_hashes
                  and len(row["full_text"].split()) >= minimum_words]
    random.Random(seed).shuffle(candidates)
    selected: list[dict[str, Any]] = []
    hashes = set(excluded_hashes)
    for row in candidates:
        if row["source_hash"] in hashes or row["normalized_text_hash"] in hashes:
            continue
        selected.append({k: v for k, v in row.items() if k not in {"full_text", "group", "membership"}})
        hashes.update((row["source_hash"], row["normalized_text_hash"]))
        if len(selected) == count:
            break
    if len(selected) != count:
        raise RuntimeError("insufficient_unused_source_capacity")
    # 先固定文档集合，再分配本实验 index 的成员身份。
    for index, row in enumerate(selected):
        row["group"] = "KB_Member" if index % 2 == 0 else "True_Non_Member"
    return selected


def validate_isolation(sources: list[dict[str, Any]], index_rows: list[dict[str, Any]]) -> None:
    if len({row["source_key"] for row in sources}) != len(sources):
        raise RuntimeError("source_key_collision")
    members = {row["source_key"] for row in sources if row["group"] == "KB_Member"}
    nonmembers = [row for row in sources if row["group"] == "True_Non_Member"]
    index_keys = {row["source_key"] for row in index_rows}
    if not members.issubset(index_keys):
        raise RuntimeError("designated_member_omitted")
    if any(row.get("group") != "KB_Member" for row in index_rows):
        raise RuntimeError("index_not_member_only")
    for field in ("source_key", "source_hash", "normalized_text_hash"):
        if {row[field] for row in nonmembers} & {row[field] for row in index_rows}:
            raise RuntimeError(f"nonmember_index_overlap:{field}")
        for group in ("KB_Member", "True_Non_Member"):
            values = [row[field] for row in sources if row["group"] == group]
            if len(set(values)) != len(values):
                raise RuntimeError(f"duplicate_source:{field}:{group}")


def answer_label(response: dict[str, Any], query: dict[str, Any]) -> str:
    return PILOT._response_label(
        response.get("response", ""), query["answer"], response.get("status", "invalid"),
        query.get("answer_aliases"),
    )


def build_frozen_queries_for_source(
    source: dict[str, Any], records: dict[str, Any], experiment_id: str,
) -> list[dict[str, Any]]:
    initial_facts = records["initial_facts"]
    target = records["remote_target"]
    anchored = records["anchored_followups"]
    remote_only = records["no_anchor_followups"]
    if not (len(initial_facts) == len(anchored) == len(remote_only) == 3):
        raise RuntimeError("shared_g_slot_count_drift")

    queries: list[dict[str, Any]] = []
    for arm, facts in (("initial", initial_facts), ("correct_anchor", anchored), ("remote_only", remote_only)):
        for index, fact in enumerate(facts):
            if arm == "correct_anchor":
                if (fact.get("anchor") != initial_facts[index]["answer"]
                        or fact.get("anchor_claim") != initial_facts[index]["claim"]
                        or fact["question"] != PILOT._anchored_question(
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
                "group": source["group"],
                "arm": arm,
                "slot_index": index,
                "question": fact["question"],
                "retrieval_query": fact["question"],
                "answer": answer_record["answer"],
                "answer_aliases": PILOT._formatting_answer_aliases(answer_record["answer"]),
                "claim": answer_record["claim"],
                "anchor": fact.get("anchor"),
                "anchor_claim": fact.get("anchor_claim"),
                "region_diagnostics": records["region_diagnostics"],
            })
    if len({row["query_id"] for row in queries}) != 9:
        raise RuntimeError("frozen_query_id_drift")
    return queries


def validate_construction(
    payload: Any, source_text: str, maximum_answer_words: int,
) -> tuple[dict[str, Any], list[str]]:
    records, reasons = PILOT._validate_generation(payload, source_text)
    if not records:
        return records, reasons
    answers = [fact["answer"] for fact in records["initial_facts"]]
    target_answer = records["remote_target"]["answer"]
    if any(len(answer.split()) > maximum_answer_words for answer in [*answers, target_answer]):
        reasons.append("answer_too_long")
    if any(PILOT._surface_present(fact["claim"], target_answer)
           for fact in records["initial_facts"]):
        reasons.append("G_answer_in_local_claim")
    return records, sorted(set(reasons))


def gated_queries(queries: list[dict[str, Any]], initial: list[dict[str, Any]]) -> list[dict[str, Any]]:
    planned = {row["query_id"]: row for row in queries if row["arm"] == "initial"}
    observed = {row["query_id"]: row for row in initial}
    if set(planned) != set(observed) or len(observed) != len(initial):
        raise RuntimeError("initial_response_set_incomplete")
    if any(row.get("status") != "completed" for row in initial):
        raise RuntimeError("initial_response_invalid_run_incomplete")
    triggered = {(query["source_key"], query["slot_index"]) for key, query in planned.items()
                 if answer_label(observed[key], query) == "correct"}
    return [row for row in queries if row["arm"] in ARMS
            and (row["source_key"], row["slot_index"]) in triggered]


def source_scores(
    sources: list[dict[str, Any]], queries: list[dict[str, Any]],
    initial: list[dict[str, Any]], followup: list[dict[str, Any]], weight: float,
) -> list[dict[str, Any]]:
    expected = gated_queries(queries, initial)
    if {row["query_id"] for row in expected} != {row["query_id"] for row in followup}:
        raise RuntimeError("followup_gate_missing_or_extra")
    responses = {row["query_id"]: row for row in initial + followup}
    if len(responses) != len(initial) + len(followup):
        raise RuntimeError("response_id_collision")
    if any(row.get("status") != "completed" for row in responses.values()):
        raise RuntimeError("invalid_response_run_incomplete")
    lookup = {(row["source_key"], row["arm"], row["slot_index"]): row for row in queries}
    rows = []
    for source in sources:
        key = source["source_key"]
        local = [int(answer_label(responses[lookup[key, "initial", i]["query_id"]],
                                  lookup[key, "initial", i]) == "correct") for i in range(3)]
        record = {"source_key": key, "dataset": source["dataset"], "group": source["group"],
                  "initial_bits": local, "local_only": sum(local)}
        for arm in ARMS:
            bits = [int(local[i] and answer_label(
                responses[lookup[key, arm, i]["query_id"]], lookup[key, arm, i]) == "correct")
                    for i in range(3)]
            record[f"{arm}_bits"] = bits
            record[arm] = sum(local) + weight * sum(bits)
        rows.append(record)
    return rows


class Successor:
    def __init__(self, config_path: Path = DEFAULT_CONFIG):
        self.config_path = config_path.resolve()
        self.config = load_yaml(self.config_path)
        self.base = load_v25_config(ROOT, self.config["base_config"])
        self.out = ROOT / self.config["output_dir"]
        self.runtime = copy.deepcopy(self.base)
        self.prompt = PILOT.GENERATION_PROMPT + "\n\n" + self.config["construction"]["prompt_appendix"]
        if tuple(self.config["query_protocol"]["arms"]) != ARMS:
            raise ValueError("successor_arm_schema_drift")
        answer_policy = self.config["answer_policy"]
        if (answer_policy.get("matcher") != "canonical_surface_v2_frozen_format_aliases"
                or answer_policy.get("aliases") != "deterministic_format_only_before_freeze"
                or answer_policy.get("post_response_alias_edits") is not False):
            raise ValueError("successor_answer_policy_drift")
        if self.config["evaluation"]["formal_release_allowed"]:
            raise ValueError("successor_is_development_only")

    def path(self, name: str) -> Path:
        return self.out / name

    def input_hashes(self) -> dict[str, str]:
        hashes = source_pool_input_hashes(ROOT, self.base)
        paths = [self.config_path, Path(__file__), PILOT_PATH,
                 ROOT / self.base["runtime"]["llm_profiles_path"],
                 ROOT / "src/prepare/restoration_first_v25.py",
                 ROOT / "src/evaluation/metrics.py", ROOT / "src/llm/factory.py",
                 ROOT / "src/llm/openai_compatible.py", ROOT / "src/llm/victim_client.py",
                 ROOT / "src/rag/embeddings.py", ROOT / "src/rag/index_builder.py"]
        hashes.update({str(path.relative_to(ROOT)): sha256_file(path) for path in paths})
        return hashes

    def profiles(self) -> dict[str, dict[str, Any]]:
        profiles = PILOT.load_llm_profiles({"llm_profiles_path": self.base["runtime"]["llm_profiles_path"]})
        values = {
            "sibling": PILOT.resolve_effective_llm_profile(profiles, "sibling", profile_name="luna_query_generator"),
            "victim": PILOT.resolve_effective_llm_profile(profiles, "victim", profile_name=self.base["runtime"]["victim_profile"]),
        }
        for role, expected in (("sibling", "gpt-6-luna"), ("victim", self.base["runtime"]["concrete_model"])):
            if values[role].get("model") != expected or not values[role].get("base_url"):
                raise RuntimeError(f"effective_profile_drift:{role}")
        return values

    def validate(self, frozen_queries: bool = False) -> dict[str, Any]:
        run = read_json(self.path("run_config.json"))
        if run["input_hashes"] != self.input_hashes():
            raise RuntimeError("frozen_code_config_or_source_pool_drift")
        for role, profile in self.profiles().items():
            if PILOT.llm_profile_identity(profile) != run["model_profiles"][role]:
                raise RuntimeError(f"frozen_effective_model_profile_drift:{role}")
        for name, digest in run["artifacts"].items():
            if sha256_file(self.path(name)) != digest:
                raise RuntimeError(f"frozen_artifact_drift:{name}")
        if frozen_queries:
            freeze = read_json(self.path("query_freeze.json"))
            for name, digest in freeze["artifacts"].items():
                if sha256_file(self.path(name)) != digest:
                    raise RuntimeError(f"frozen_query_artifact_drift:{name}")
        return run

    def pool(self, dataset: str) -> list[dict[str, Any]]:
        paths = source_pool_paths(ROOT, self.base, dataset)
        ordered = read_json(paths["source_order"])["source_order"]
        with sqlite3.connect(paths["database"]) as connection:
            fetched = connection.execute(
                "SELECT source_key,dataset,document_id,source_order_rank,source_hash,normalized_text_hash,full_text FROM sources"
            ).fetchall()
        fields = ("source_key", "dataset", "document_id", "source_order_rank", "source_hash", "normalized_text_hash", "full_text")
        by_key = {str(row[0]): dict(zip(fields, map(str, row))) for row in fetched}
        return [by_key[key] for key in ordered]

    def prepare(self) -> None:
        if self.path("run_config.json").is_file():
            self.validate()
            print(json.dumps({"stage": "prepare", "status": "already_prepared"}), flush=True)
            return
        if self.out.exists() and any(self.out.iterdir()):
            raise RuntimeError("refuse_overwrite_partial_prepare")
        files = sorted({* (ROOT / "artifacts/v25").rglob("source_manifest.jsonl"),
                        * (ROOT / "artifacts/v25").rglob("source_plan.json"),
                        * (ROOT / "artifacts/v25").rglob("source_split.json")})
        used: set[str] = set()
        for path in files:
            if self.out in path.parents:
                continue
            payload = read_rows(path) if path.suffix == ".jsonl" else read_json(path)
            used.update(identity_keys(payload))
        pools = {dataset: self.pool(dataset) for dataset in self.base["datasets"]}
        excluded_hashes = {row[field] for rows in pools.values() for row in rows
                           if row["source_key"] in used for field in ("source_hash", "normalized_text_hash")}
        sources, indices = [], []
        for offset, dataset in enumerate(self.base["datasets"]):
            paths = source_pool_paths(ROOT, self.base, dataset)
            exclusions = read_json(paths["development_exclusions"])["exclusions"]
            excluded_keys = used | {row["source_key"] for row in exclusions}
            selected = select_blind_sources(
                pools[dataset], int(self.config["source_selection"]["dataset_counts"][dataset]),
                self.config["seed"] + offset, self.config["source_selection"]["minimum_words"],
                excluded_keys, excluded_hashes,
            )
            sources.extend(selected)
            excluded_hashes.update(row[field] for row in selected for field in ("source_hash", "normalized_text_hash"))
            designated = [row for row in selected if row["group"] == "KB_Member"]
            fill = select_blind_sources(
                pools[dataset], self.config["index"]["member_sources_per_dataset"] - len(designated),
                self.config["seed"] + offset + 1000, 1,
                excluded_keys | {row["source_key"] for row in selected}, excluded_hashes,
            )
            indices.extend(designated + [{**row, "group": "KB_Member"} for row in fill])
            excluded_hashes.update(row[field] for row in fill for field in ("source_hash", "normalized_text_hash"))
        validate_isolation(sources, indices)
        for row in sources + indices:
            read_source_text(ROOT, self.base, row)
        self.out.mkdir(parents=True, exist_ok=True)
        write_jsonl_atomic(sources, self.path("source_manifest.jsonl"))
        write_json({"source_unit": "source_document", "index_member_only": True,
                    "sources": indices}, self.path("index_manifest.json"))
        run = {
            "experiment_id": self.config["experiment_id"], "status": "fixed_before_new_calls",
            "development_only": True, "no_formal_test_claim": True,
            "config": self.config, "input_hashes": self.input_hashes(),
            "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "uncommitted_code_bound_by_sha256": True,
            "source_unit": "source_document", "source_count": len(sources),
            "group_counts": dict(Counter(row["group"] for row in sources)),
            "dataset_counts": dict(Counter(row["dataset"] for row in sources)),
            "selection": {"membership_labels_read": False, "victim_or_retrieval_results_read": False,
                          "historical_source_count": len(used), "historical_source_keys_sha256": sha256_obj(sorted(used)),
                          "historical_identity_files": [str(p.relative_to(ROOT)) for p in files],
                          "role_assignment": "after_content_only_source_selection", "replacement": False},
            "model_profiles": {role: PILOT.llm_profile_identity(profile) for role, profile in self.profiles().items()},
            "prompts": {"construction_sha256": sha256_text(self.prompt),
                        "repair_sha256": sha256_text(self.prompt + "\n\n" + PILOT.REPAIR_SUFFIX),
                        "rag_sha256": sha256_text(PILOT.RAG_PROMPT)},
            "runtime": self.base["runtime"],
            "maximum_calls": {"luna": 2 * len(sources), "victim": 9 * len(sources)},
            "artifacts": {name: sha256_file(self.path(name)) for name in ("source_manifest.jsonl", "index_manifest.json")},
        }
        write_json(run, self.path("run_config.json"))
        print(json.dumps({"stage": "prepare", "sources": len(sources), "groups": run["group_counts"],
                          "datasets": run["dataset_counts"], "index_sources": len(indices),
                          "historical_sources_excluded": len(used), "external_calls": 0}), flush=True)

    def generate(self, max_new: int, retry_failed: bool = False) -> None:
        self.validate()
        if self.path("query_freeze.json").exists():
            raise RuntimeError("generation_already_frozen")
        sources = read_rows(self.path("source_manifest.jsonl"))
        saved = {row["source_key"]: row for row in read_rows(self.path("generation.jsonl"))}
        pending = [row for row in sources if row["source_key"] not in saved or
                   (retry_failed and saved[row["source_key"]]["status"] != "passed"
                    and 1 + len(saved[row["source_key"]].get("attempt_history", []))
                    < self.config["construction"]["maximum_attempts_per_source"])][:max_new]
        profiles = PILOT.load_llm_profiles({"llm_profiles_path": self.base["runtime"]["llm_profiles_path"]})
        client, profile = PILOT.build_role_chat_client(profiles, "sibling", profile_name="luna_query_generator")
        client.max_retries, client.retry_until_success = 0, False
        for source in pending:
            key = source["source_key"]
            previous = saved.get(key)
            history = list(previous.get("attempt_history", [])) if previous else []
            if previous:
                history.append({k: v for k, v in previous.items() if k != "attempt_history"})
            text = read_source_text(ROOT, self.base, source)
            prompt = PILOT._build_construction_prompt(text, self.prompt, previous)
            row = {"source_key": key, "source_hash": source["source_hash"], "status": "attempt_started",
                   "prompt_sha256": sha256_text(prompt), "attempt_history": history,
                   "profile_identity": PILOT.llm_profile_identity(profile)}
            saved[key] = row
            write_jsonl_atomic([saved[s["source_key"]] for s in sources if s["source_key"] in saved], self.path("generation.jsonl"))
            try:
                result = client.chat_with_metadata(prompt, temperature=self.config["construction"]["temperature"],
                    max_tokens=self.config["construction"]["max_tokens"], timeout=profile["timeout"])
                row.update({"raw_response": result.content, "response_sha256": sha256_text(result.content),
                            "provider_model_id": result.provider_model_id, "provider_request_id": result.provider_request_id,
                            "system_fingerprint": result.system_fingerprint, "called_at": result.called_at})
                if result.provider_model_id != "gpt-6-luna":
                    row["status"] = "provider_model_drift"
                else:
                    payload, parse_diagnostics = PILOT._parse_json_with_diagnostics(result.content)
                    records, reasons = validate_construction(
                        payload, text, self.config["construction"]["maximum_answer_words"],
                    )
                    row.update({"records": records, "quality_reasons": sorted(set(reasons)),
                                "parse_diagnostics": parse_diagnostics,
                                "status": "passed" if not reasons else "failed_quality_gate"})
            except Exception as exc:
                row.update({"status": "invalid_generation" if "raw_response" in row else "uncertain_transport",
                            "error_type": type(exc).__name__})
            write_jsonl_atomic([saved[s["source_key"]] for s in sources if s["source_key"] in saved], self.path("generation.jsonl"))
            print(json.dumps({"stage": "generation", "source_key": key, "status": row["status"],
                              "reasons": row.get("quality_reasons", [])}), flush=True)
            if row["status"] == "provider_model_drift":
                raise RuntimeError("stop_after_luna_provider_model_drift")
        print(json.dumps({"stage": "generation", "new_calls": len(pending),
                          "statuses": dict(Counter(row["status"] for row in saved.values()))}), flush=True)

    def review_packet(self, start: int, count: int) -> None:
        self.validate()
        rows = [row for row in read_rows(self.path("generation.jsonl")) if row["status"] == "passed"]
        for row in rows[start:start + count]:
            print(json.dumps({"source_key": row["source_key"], "records": row["records"]}, ensure_ascii=False))
        print(json.dumps({"generation_sha256": sha256_file(self.path("generation.jsonl")), "passed": len(rows)}))

    def freeze(self) -> None:
        self.validate()
        if self.path("query_freeze.json").exists():
            self.validate(True)
            print(json.dumps({"stage": "freeze", "status": "already_frozen"}), flush=True)
            return
        sources = read_rows(self.path("source_manifest.jsonl"))
        generations = read_rows(self.path("generation.jsonl"))
        by_key = {row["source_key"]: row for row in generations}
        if set(by_key) != {row["source_key"] for row in sources} or len(by_key) != len(generations):
            raise RuntimeError("construction_incomplete")
        review = read_json(self.path("semantic_review.json"))
        if review.get("reviewer_type") != "assistant_membership_blind" or review.get("generation_sha256") != sha256_file(self.path("generation.jsonl")):
            raise RuntimeError("offline_semantic_review_missing_or_drift")
        passed = {row["source_key"] for row in generations if row["status"] == "passed"}
        accepted = set(review["accepted_source_keys"])
        rejected = set(review["rejected_sources"])
        if accepted & rejected or accepted | rejected != passed:
            raise RuntimeError("offline_semantic_review_coverage_incomplete")
        queries = []
        for source in sources:
            if source["source_key"] not in accepted:
                continue
            records = by_key[source["source_key"]]["records"]
            replay_payload = PILOT._parse_json(by_key[source["source_key"]]["raw_response"])
            replayed, reasons = validate_construction(
                replay_payload, read_source_text(ROOT, self.base, source),
                self.config["construction"]["maximum_answer_words"],
            )
            if reasons or replayed != records:
                raise RuntimeError("generation_offline_replay_drift")
            queries.extend(build_frozen_queries_for_source(
                source, records, self.config["experiment_id"],
            ))
        if len(queries) != 9 * len(accepted) or len({q["query_id"] for q in queries}) != len(queries):
            raise RuntimeError("frozen_query_count_drift")
        write_jsonl_atomic(queries, self.path("query_plan.jsonl"))
        write_json({"status": "frozen_before_retrieval_and_victim", "accepted_source_count": len(accepted),
                    "construction_failures": len(sources) - len(passed), "semantic_rejections": len(rejected),
                    "no_replacements": True, "scoring": self.config["scoring"],
                    "evaluation": self.config["evaluation"], "answer_policy": self.config["answer_policy"],
                    "artifacts": {name: sha256_file(self.path(name)) for name in
                                  ("run_config.json", "generation.jsonl", "semantic_review.json", "query_plan.jsonl")}},
                   self.path("query_freeze.json"))
        print(json.dumps({"stage": "freeze", "accepted_sources": len(accepted), "queries": len(queries),
                          "construction_failures": len(sources) - len(passed), "semantic_rejections": len(rejected)}), flush=True)

    def install_retrieval(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        self.validate(True)
        queries = read_rows(self.path("query_plan.jsonl"))
        sources = read_rows(self.path("source_manifest.jsonl"))
        indices = read_json(self.path("index_manifest.json"))["sources"]
        validate_isolation(sources, indices)
        for row in indices:
            row["full_text"] = read_source_text(ROOT, self.base, row)
        PILOT.V25_CONFIG, PILOT.DATASETS = self.runtime, tuple(self.base["datasets"])
        PILOT.QUERY_PLAN, PILOT.RETRIEVAL = self.path("query_plan.jsonl"), self.path("retrieval.jsonl")
        PILOT._fixed_queries = lambda: queries
        PILOT._source_pool_member_rows = lambda dataset: [row for row in indices if row["dataset"] == dataset]
        return queries, indices

    def retrieval_map(self) -> dict[str, dict[str, Any]]:
        queries, indices = self.install_retrieval()
        rows = read_rows(self.path("retrieval.jsonl"))
        observed = {row["query_id"]: row for row in rows}
        if set(observed) != {row["query_id"] for row in queries} or len(observed) != len(rows):
            raise RuntimeError("retrieval_incomplete")
        allowed = {row["source_key"]: row for row in indices}
        plan_hash = sha256_file(self.path("query_plan.jsonl"))
        for row in rows:
            if row["query_plan_sha256"] != plan_hash:
                raise RuntimeError("retrieval_query_hash_drift")
            members = [r for r in indices if r["dataset"] == row["dataset"]]
            if row["index_identity"] != sha256_obj([(r["source_key"], r["source_hash"]) for r in members]):
                raise RuntimeError("retrieval_index_hash_drift")
            for chunk in row["retrieved_chunks"]:
                source = allowed.get(chunk["source_key"])
                if not source or source["dataset"] != row["dataset"] or chunk["source_hash"] != source["source_hash"]:
                    raise RuntimeError("retrieval_nonmember_or_source_hash_drift")
        return observed

    def retrieve(self) -> None:
        self.install_retrieval()
        PILOT.retrieve()
        self.retrieval_map()

    def run_victim(self, followup: bool, max_new: int) -> None:
        retrieval = self.retrieval_map()
        queries = read_rows(self.path("query_plan.jsonl"))
        planned = gated_queries(queries, read_rows(self.path("initial_responses.jsonl"))) if followup else [q for q in queries if q["arm"] == "initial"]
        name = "followup_responses.jsonl" if followup else "initial_responses.jsonl"
        saved_rows = read_rows(self.path(name))
        saved = {row["query_id"]: row for row in saved_rows}
        if len(saved) != len(saved_rows) or set(saved) - {q["query_id"] for q in planned}:
            raise RuntimeError("saved_response_set_drift")
        retrieval_hash = sha256_file(self.path("retrieval.jsonl"))
        for row in saved.values():
            if row["retrieval_sha256"] != retrieval_hash or row["status"] != "completed":
                raise RuntimeError("response_invalid_or_retrieval_drift_resume_refused")
            if row["response_sha256"] != sha256_text(row["response"]):
                raise RuntimeError("response_hash_drift")
        pending = [q for q in planned if q["query_id"] not in saved][:max_new]
        profiles = PILOT.load_llm_profiles({"llm_profiles_path": self.base["runtime"]["llm_profiles_path"]})
        client, profile = PILOT.build_victim_client(profiles, profile_name=self.base["runtime"]["victim_profile"])
        for query in pending:
            found = retrieval[query["query_id"]]
            context = "\n\n---\n\n".join(chunk["text"] for chunk in found["retrieved_chunks"])
            prompt = PILOT.RAG_PROMPT.format(contexts=context, query=query["question"])
            if sha256_text(prompt) != found["prompt_sha256"] or sha256_text(context) != found["context_sha256"]:
                raise RuntimeError("victim_prompt_or_context_drift")
            row = {"query_id": query["query_id"], "source_key": query["source_key"], "arm": query["arm"],
                   "slot_index": query["slot_index"], "status": "attempt_started",
                   "retrieval_sha256": retrieval_hash, "prompt_sha256": found["prompt_sha256"]}
            saved[query["query_id"]] = row
            write_jsonl_atomic([saved[q["query_id"]] for q in planned if q["query_id"] in saved], self.path(name))
            try:
                result = client.generate_with_metadata(prompt, temperature=self.base["runtime"]["generation"]["temperature"],
                    max_tokens=self.base["runtime"]["generation"]["max_tokens"], timeout=profile["timeout"])
                row.update({"status": "completed" if result.provider_model_id == profile["model"] else "provider_model_drift",
                            "response": result.content, "response_sha256": sha256_text(result.content),
                            "provider_model_id": result.provider_model_id, "provider_request_id": result.provider_request_id,
                            "called_at": result.called_at, "system_fingerprint": result.system_fingerprint,
                            "profile_identity": PILOT.llm_profile_identity(profile)})
            except Exception as exc:
                row.update({"status": "uncertain_transport", "error_type": type(exc).__name__})
            write_jsonl_atomic([saved[q["query_id"]] for q in planned if q["query_id"] in saved], self.path(name))
            print(json.dumps({"stage": name[:-6], "done": len(saved), "planned": len(planned),
                              "status": row["status"]}), flush=True)
            if row["status"] != "completed":
                raise RuntimeError("victim_invalid_response_stop_preserve_evidence")
            time.sleep(self.base["runtime"]["generation"]["request_interval_seconds"])
        print(json.dumps({"stage": name[:-6], "new_calls": len(pending), "total": len(saved), "planned": len(planned)}), flush=True)

    def metrics(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        seed, boot = self.config["seed"], self.config["evaluation"]["bootstrap_samples"]
        initial = rates_at_threshold(rows, self.config["scoring"]["initial_gate_points"], score_key="local_only")
        minimum_fp_capacity = self.config["evaluation"].get("minimum_initial_false_positive_sources")
        for arm in ("local_only",) + ARMS:
            cutoff = self.config["scoring"]["operational_cutoff"]
            rates = rates_at_threshold(rows, cutoff, score_key=arm)
            falsepositives = [r for r in rows if r["group"] == "True_Non_Member" and r["local_only"] >= self.config["scoring"]["initial_gate_points"]]
            corrected = sum(r[arm] < cutoff for r in falsepositives)
            output[arm] = {
                "auc": roc_auc(rows, score_key=arm), "auc_bootstrap": bootstrap_auc_ci(rows, score_key=arm, seed=seed, n_bootstrap=boot),
                "cutoff_metrics": rates,
                "fpr_ci95": clopper_pearson_interval(rates["false_positive_count"], rates["negative_count"]),
                "tpr_ci95": clopper_pearson_interval(rates["true_positive_count"], rates["positive_count"]),
                "initial_gate_metrics": initial,
                "initial_false_positive_sources": len(falsepositives), "corrected_sources": corrected,
                "correction_rate": corrected / len(falsepositives) if falsepositives else None,
                "correction_ci95": clopper_pearson_interval(corrected, len(falsepositives)),
                "correction_capacity_minimum": minimum_fp_capacity,
                "correction_capacity_sufficient": (
                    None if minimum_fp_capacity is None else len(falsepositives) >= minimum_fp_capacity
                ),
                "member_retention": rates["true_positive_count"] / initial["true_positive_count"] if initial["true_positive_count"] else None,
                "member_tpr_cost_pp": 100 * (initial["TPR"] - rates["TPR"]),
                "low_fpr": {str(target): tpr_at_fpr_details(threshold_curve(rows, score_key=arm), target)
                            for target in self.config["evaluation"]["low_fpr_targets"]},
                "score_distribution": {group: dict(Counter(str(r[arm]) for r in rows if r["group"] == group))
                                       for group in ("KB_Member", "True_Non_Member")},
            }
        return output

    def report(self) -> None:
        self.validate(True)
        queries = read_rows(self.path("query_plan.jsonl"))
        accepted = {q["source_key"] for q in queries}
        all_sources = read_rows(self.path("source_manifest.jsonl"))
        sources = [s for s in all_sources if s["source_key"] in accepted]
        initial, follow = read_rows(self.path("initial_responses.jsonl")), read_rows(self.path("followup_responses.jsonl"))
        rows = source_scores(sources, queries, initial, follow, self.config["scoring"]["lambda"])
        retrieval = self.retrieval_map()
        by_dataset = {d: [r for r in rows if r["dataset"] == d] for d in self.base["datasets"]}
        metrics = self.metrics(rows)
        result = {
            "experiment_id": self.config["experiment_id"], "status": "fresh_development_validation_complete",
            "development_only": True, "no_formal_test_claim": True, "source_unit": "source_document",
            "original_source_count": len(all_sources), "evaluated_source_count": len(rows),
            "group_counts": dict(Counter(r["group"] for r in rows)),
            "construction_failures_not_replaced": len(all_sources) - len(rows),
            "calls": {"luna": sum(1 + len(r.get("attempt_history", [])) for r in read_rows(self.path("generation.jsonl"))),
                      "retrieval": len(retrieval), "victim_initial": len(initial), "victim_followup": len(follow)},
            "source_scores": rows, "metrics": metrics, "dataset_metrics": {d: self.metrics(v) for d, v in by_dataset.items()},
            "macro_auc": {arm: bootstrap_macro_auc_ci(by_dataset, score_key=arm,
                         n_bootstrap=self.config["evaluation"]["bootstrap_samples"], seed=self.config["seed"])
                          for arm in ("local_only",) + ARMS},
            "label_counts": dict(Counter(f'{q["arm"]}:{answer_label(r, q)}' for r in initial + follow
                                          for q in [next(q for q in queries if q["query_id"] == r["query_id"])])),
            "retrieval_diagnostics": {f"{g}:{arm}": {"queries": len(selected),
                      "target_source_hit_count": sum(bool(r["target_source_chunk_ranks"]) for r in selected),
                      "answer_surface_hit_count": sum(bool(r["answer_surface_chunk_ranks"]) for r in selected)}
                      for g in ("KB_Member", "True_Non_Member") for arm in ("initial",) + ARMS
                      for selected in [[retrieval[q["query_id"]] for q in queries if q["group"] == g and q["arm"] == arm]]},
            "gate_audit": {"triggered_slots": len(follow) // 2, "expected_followup_calls": len(gated_queries(queries, initial)),
                           "observed_followup_calls": len(follow), "missing": 0, "extra": 0},
            "interpretation": {
                "correction": "Initial gate=1 versus final cutoff=2 includes a threshold change. Compare local_only at cutoff=2 to identify that contribution.",
                "additive_score": "Nonnegative G points cannot remove a local_only cutoff=2 false positive; they can retain one-local-hit Members or admit Non-members.",
                "shared_G": "Repeated G probes are correlated; all uncertainty is computed at source level.",
                "capacity": "Below 20 initial false-positive sources, correction is reported only as feasibility.",
                "annotation": "Assistant membership-blind review; no independent human annotation is claimed.",
            },
            "artifact_hashes": {name: sha256_file(self.path(name)) for name in
                ("run_config.json", "source_manifest.jsonl", "index_manifest.json", "query_freeze.json", "query_plan.jsonl",
                 "generation.jsonl", "semantic_review.json", "retrieval.jsonl", "initial_responses.jsonl", "followup_responses.jsonl")},
        }
        if self.path("report.json").exists():
            if read_json(self.path("report.json")) != json.loads(json.dumps(result)):
                raise RuntimeError("refuse_overwrite_different_result")
        else:
            write_json(result, self.path("report.json"))
        print(json.dumps({"stage": "report", "sources": len(rows), "calls": result["calls"],
                          "aucs": {arm: metrics[arm]["auc"] for arm in metrics},
                          "initial_false_positives": metrics["correct_anchor"]["initial_false_positive_sources"]}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("prepare", "generate", "retry-failed", "review-packet", "freeze", "retrieve", "run-initial", "run-followup", "report"):
        modes.add_argument(f"--{mode}", action="store_true")
    parser.add_argument("--max-new", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()
    if args.generate or args.retry_failed or args.run_initial or args.run_followup:
        if args.max_new < 1:
            parser.error("calls require --max-new >= 1")
    elif args.max_new:
        parser.error("--max-new applies only to calls")
    runner = Successor(args.config)
    if args.prepare:
        runner.prepare()
    elif args.generate or args.retry_failed:
        runner.generate(args.max_new, args.retry_failed)
    elif args.review_packet:
        runner.review_packet(args.start, args.count)
    elif args.freeze:
        runner.freeze()
    elif args.retrieve:
        runner.retrieve()
    elif args.run_initial or args.run_followup:
        runner.run_victim(args.run_followup, args.max_new)
    else:
        runner.report()


if __name__ == "__main__":
    main()
