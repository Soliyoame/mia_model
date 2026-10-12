"""正式配置与有效模型 profile；读取配置不会创建网络客户端。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.llm.factory import load_llm_profiles, resolve_effective_llm_profile
from src.utils.io import load_yaml


@dataclass(frozen=True)
class ExperimentConfig:
    root: Path
    path: Path
    data: dict[str, Any]

    @property
    def datasets(self) -> tuple[str, ...]:
        return tuple(self.data["datasets"])

    @property
    def output(self) -> Path:
        return self.resolve(self.data["output_dir"])

    def resolve(self, value: str) -> Path:
        return (self.root / value).resolve()

    def pool_paths(self, dataset: str) -> dict[str, Path]:
        if dataset not in self.datasets:
            raise ValueError("unknown_dataset")
        return {key: self.resolve(value.format(dataset=dataset))
                for key, value in self.data["source_pool"]["paths"].items()}

    def profiles(self) -> dict[str, dict[str, Any]]:
        profiles = load_llm_profiles({"llm_profiles_path": str(self.resolve(
            self.data["runtime"]["llm_profiles_path"]))})
        runtime = self.data["runtime"]
        result = {
            "sibling": resolve_effective_llm_profile(
                profiles, "sibling", profile_name=self.data["query_generator"]["profile"]),
            "victim": resolve_effective_llm_profile(
                profiles, "victim", profile_name=runtime["victim_profile"]),
        }
        for role, expected in (("sibling", self.data["query_generator"]["configured_model"]),
                               ("victim", runtime["concrete_model"])):
            if result[role].get("model") != expected:
                raise RuntimeError(f"effective_model_profile_drift:{role}")
        return result


def load_config(path: str | Path, root: Path | None = None) -> ExperimentConfig:
    project = (root or Path(__file__).resolve().parents[2]).resolve()
    target = (project / path).resolve()
    data = load_yaml(target)
    if data.get("run_role") != "formal" or data.get("protocol_version") != "pcv-mia-v25":
        raise ValueError("formal_protocol_required")
    datasets = data["datasets"]
    if datasets != ["nfcorpus", "scidocs", "trec-covid"]:
        raise ValueError("formal_dataset_order_drift")
    selection = data["source_selection"]
    if (selection["replacement_after_freeze"] is not False
            or selection["selection_mode"] != "qualified_before_membership"
            or selection["membership_assignment"] != "alternating_after_qualified_shuffle"
            or selection["minimum_words"] < 1):
        raise ValueError("source_selection_policy_drift")
    if selection.get("allow_v24_raw_document_reuse") is not True:
        raise ValueError("explicit_v24_raw_reuse_binding_required")
    if selection.get("allow_history_raw_document_reuse") is not True:
        raise ValueError("explicit_history_raw_reuse_binding_required")
    for name in datasets:
        counts = selection["counts"][name]
        if (set(counts) != {"KB_Member", "True_Non_Member"} or counts["KB_Member"] < 1
                or counts["KB_Member"] != counts["True_Non_Member"]
                or data["index"]["member_sources_per_dataset"][name] != counts["KB_Member"]):
            raise ValueError("balanced_members_and_fixed_index_required")
    protocol = data["query_protocol"]
    if (protocol["arms"] != ["correct_anchor", "remote_only"] or protocol["local_slots"] != 3
            or protocol["anchor_context"] != "exact_paired_local_claim"
            or protocol["followup_gate"] != "initial_response_correct_per_slot"
            or protocol["query_budget"] != "3 + 2 * sum(I_i)"):
        raise ValueError("query_protocol_drift")
    policy = data["answer_policy"]
    if (policy["matcher"] not in {"canonical_surface_v2_frozen_format_aliases",
                                  "canonical_surface_v3_token_boundaries_scoped_abstention"}
            or policy["aliases"] != "deterministic_format_only_before_freeze"
            or policy["post_response_alias_edits"] is not False
            or policy["ambiguous"] != "zero_points_no_trigger"
            or policy["invalid"] != "incomplete_run_no_final_metrics"):
        raise ValueError("answer_policy_drift")
    if policy.get("response_adjudications") is not None and (
            policy["response_adjudications"] != "response_adjudications.json"
            or policy["matcher"] != "canonical_surface_v3_token_boundaries_scoped_abstention"):
        raise ValueError("response_adjudication_policy_drift")
    scoring = data["scoring"]
    if (scoring["primary"] != "S_lambda" or scoring["lambda"] != 1.0
            or scoring["operational_cutoff"] != 2.0
            or scoring["statistical_unit"] != "source_document"):
        raise ValueError("formal_scoring_drift")
    construction = data["construction"]
    if (construction["maximum_attempts_per_source"] != 2 or construction["transport_retry_until_success"] is not True
            or construction["maximum_total_calls"] < 1
            or construction["maximum_answer_words"] != 12):
        raise ValueError("construction_budget_drift")
    review = data.get("semantic_review")
    if review is not None and (
            review["reviewer_type"] != "ai_membership_blind"
            or review["acceptance_policy"] != "usable_without_obvious_errors"
            or review["profile"] != data["query_generator"]["profile"]
            or review["configured_model"] != data["query_generator"]["configured_model"]
            or not 1 <= review["batch_size"] <= 10
            or review["temperature"] != 0.0 or review["max_tokens"] < 1
            or review["transport_retry_until_success"] is not True):
        raise ValueError("semantic_review_configuration_drift")
    evaluation = data["evaluation"]
    if (evaluation["primary"] != "macro_source_auc" or evaluation["confidence"] != 0.95
            or evaluation["bootstrap_samples"] < 1):
        raise ValueError("evaluation_policy_drift")
    if data["runtime"]["generation"]["retries"] != 0:
        raise ValueError("automatic_victim_retries_forbidden")
    retrieval = data["runtime"]["retrieval"]
    if (retrieval["backend"] != "dense" or not retrieval["revision"]
            or not 0 <= retrieval["chunk_overlap"] < retrieval["chunk_size"] or retrieval["top_k"] != 5):
        raise ValueError("unsupported_retriever_configuration")
    config = ExperimentConfig(project, target, data)
    allowed = (project / "artifacts/v25/formal").resolve()
    if not config.output.is_relative_to(allowed) or config.output == allowed:
        raise ValueError("independent_formal_output_required")
    reused = data.get("reused_inputs")
    if reused is not None:
        if (set(reused) != {"source_dir", "retrieval_dirs"}
                or set(reused["retrieval_dirs"]) != set(datasets)
                or policy.get("response_adjudications") is not None):
            raise ValueError("fixed_inputs_without_old_response_adjudications_required")
        for directory in (reused["source_dir"], *reused["retrieval_dirs"].values()):
            source = config.resolve(directory)
            if (not source.is_relative_to(allowed) or source == allowed
                    or source.is_relative_to(config.output) or config.output.is_relative_to(source)):
                raise ValueError("independent_reused_input_directory_required")
    return config
