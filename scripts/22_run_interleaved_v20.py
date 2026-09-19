"""Run the 90,000-call v20 main matrix in frozen source-adjacent blocks."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.factory import build_victim_client, load_llm_profiles, resolve_llm_profile_name  # noqa: E402
from src.llm.generator_registry import (  # noqa: E402
    load_and_resolve_frozen_generator,
    record_first_formal_call,
)
from src.rag.paths import retriever_id_from_config, retriever_index_dir  # noqa: E402
from src.rag.retriever import HybridRagRetriever, RagRetriever  # noqa: E402
from src.rag.runner import TokenBucket, response_is_success, run_rag_and_llm_only  # noqa: E402
from src.utils.hash import sha256_file  # noqa: E402
from src.utils.io import load_yaml, read_json, read_jsonl, resolve_path  # noqa: E402
from src.utils.run_context import (  # noqa: E402
    experiment_scoped_dir,
    git_snapshot,
    require_clean_release_commit,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run frozen interleaved v20 matrix")
    parser.add_argument("--config", default="configs/rag_config.yaml")
    parser.add_argument("--victim-profile")
    parser.add_argument("--checkpoint-every", type=int, default=200)
    return parser.parse_args()


def _successful(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        str(row["query_id"])
        for row in read_jsonl(path)
        if response_is_success(row)
    }


def main() -> int:
    args = parse_args()
    config = load_yaml(args.config)
    schedule_path = resolve_path(config["paths"]["execution_schedule_path"])
    schedule_manifest = read_json(
        resolve_path(config["paths"]["execution_schedule_manifest_path"])
    )
    schedule_hash = sha256_file(schedule_path)
    if schedule_hash != str(schedule_manifest.get("schedule_hash") or ""):
        raise RuntimeError("Frozen execution schedule hash mismatch")
    profiles = load_llm_profiles(config)
    profile_name = resolve_llm_profile_name(
        "victim",
        cli_profile=args.victim_profile,
        config_profile=config.get("generation", {}).get("victim_profile"),
    )
    client, profile = build_victim_client(profiles, profile_name=profile_name)
    generator = load_and_resolve_frozen_generator(
        family="llama",
        concrete_model=str(profile.get("model") or ""),
        provider=str(profile.get("provider") or ""),
        generator_version=profile.get("model_version"),
        path=config.get("generator_registry_path", "configs/generator_families.yaml"),
    )
    rows = list(read_jsonl(schedule_path))
    ordinals: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    block_cells: dict[str, list[str]] = defaultdict(list)
    block_queries: dict[tuple[str, str], set[str]] = defaultdict(set)
    block_dataset: dict[str, str] = {}
    block_first: dict[str, int] = {}
    for row in rows:
        dataset = str(row["dataset"])
        cell = str(row["cell"])
        block = str(row["block_id"])
        query_id = str(row["query_id"])
        ordinal = int(row["ordinal"])
        ordinals[(dataset, cell)][query_id] = ordinal
        block_queries[(block, cell)].add(query_id)
        block_dataset[block] = dataset
        block_first.setdefault(block, ordinal)
        if cell not in block_cells[block]:
            block_cells[block].append(cell)
    gen_cfg = config["generation"]
    shared_bucket = TokenBucket(float(gen_cfg["requests_per_minute"]))
    retrievers: dict[tuple[str, str], object] = {}
    output_paths: dict[tuple[str, str], Path] = {}
    done: dict[tuple[str, str], set[str]] = {}
    for dataset in ("edgar", "enron", "pubmed"):
        dense = RagRetriever(retriever_index_dir(config, dataset, "dense"))
        bm25 = RagRetriever(retriever_index_dir(config, dataset, "bm25"))
        hybrid_cfg = config["retrieval"]["hybrid"]
        hybrid = HybridRagRetriever(
            retriever_index_dir(config, dataset, "dense"),
            retriever_index_dir(config, dataset, "bm25"),
            dense_candidate_top_k=int(hybrid_cfg["dense_candidate_top_k"]),
            bm25_candidate_top_k=int(hybrid_cfg["bm25_candidate_top_k"]),
            rrf_k=int(hybrid_cfg["rrf_k"]),
            fusion_top_k=int(hybrid_cfg["fusion_top_k"]),
            final_top_k=int(hybrid_cfg["final_top_k"]),
            reranker_model=str(hybrid_cfg["reranker_model"]),
            reranker_revision=hybrid_cfg.get("reranker_revision"),
            reranker_local_files_only=bool(
                hybrid_cfg.get("reranker_local_files_only", True)
            ),
        )
        for cell, retriever in (
            ("dense", dense),
            ("bm25", bm25),
            ("hybrid", hybrid),
        ):
            retrievers[(dataset, cell)] = retriever
            retriever_id = retriever_id_from_config(config, cell)
            output = (
                experiment_scoped_dir(
                    config["paths"]["rag_responses_dir"],
                    dataset,
                    generator_family="llama",
                    concrete_model=generator.concrete_model,
                    retriever_id=retriever_id,
                )
                / f"{dataset}_rag_responses.jsonl"
            )
            output_paths[(dataset, cell)] = output
            done[(dataset, cell)] = _successful(output)
        llm_output = (
            experiment_scoped_dir(
                config["paths"]["llm_only_responses_dir"],
                dataset,
                generator_family="llama",
                concrete_model=generator.concrete_model,
                retriever_id="none",
            )
            / f"{dataset}_llm_only_responses.jsonl"
        )
        output_paths[(dataset, "none")] = llm_output
        done[(dataset, "none")] = _successful(llm_output)
    fingerprints: set[str] = set()
    code_commit = require_clean_release_commit(git_snapshot())
    freeze_state_recorded = False
    for block in sorted(block_first, key=block_first.get):
        dataset = block_dataset[block]
        queries_path = (
            resolve_path(config["paths"]["queries_dir"])
            / f"{dataset}_paired_queries.jsonl"
        )
        benchmark_path = (
            resolve_path(config["paths"]["benchmark_dir"])
            / f"{dataset}_attack_benchmark.jsonl"
        )
        for cell in block_cells[block]:
            query_ids = block_queries[(block, cell)]
            if query_ids <= done[(dataset, cell)]:
                continue
            is_llm = cell == "none"
            retriever = None if is_llm else retrievers[(dataset, cell)]
            retriever_id = "none" if is_llm else retriever_id_from_config(config, cell)
            rag_output = (
                output_paths[(dataset, cell)]
                if not is_llm
                else output_paths[(dataset, "dense")].with_name("_unused_rag.jsonl")
            )
            llm_output = (
                output_paths[(dataset, "none")]
                if is_llm
                else output_paths[(dataset, "none")].with_name("_unused_llm.jsonl")
            )
            manifest = run_rag_and_llm_only(
                dataset=dataset,
                queries_path=queries_path,
                benchmark_path=benchmark_path,
                index_dir=(
                    retriever_index_dir(config, dataset, cell)
                    if cell in {"dense", "bm25"}
                    else resolve_path(config["paths"]["indexes_dir"]) / dataset
                ),
                rag_output_path=rag_output,
                llm_output_path=llm_output,
                client=client,
                top_k=int(config["retrieval"]["top_k"]),
                temperature=float(gen_cfg["temperature"]),
                max_tokens=int(gen_cfg["max_tokens"]),
                timeout=float(gen_cfg["timeout"]),
                retries=int(gen_cfg["retries"]),
                retry_backoff_base=float(gen_cfg["retry_backoff_base"]),
                retry_backoff_max=float(gen_cfg["retry_backoff_max"]),
                retry_until_success=bool(gen_cfg["retry_until_success"]),
                retry_cooldown_seconds=float(gen_cfg["retry_cooldown_seconds"]),
                max_workers=1,
                resume=True,
                force=False,
                run_rag=not is_llm,
                run_llm_only=is_llm,
                requests_per_minute=0.0,
                checkpoint_every=args.checkpoint_every,
                pairs_per_source=3,
                generator_id=generator.concrete_model,
                generator_version=generator.generator_version,
                generator_family="llama",
                concrete_model=generator.concrete_model,
                code_commit=code_commit,
                retriever_override=retriever,
                retriever_identity_override=retriever_id,
                schedule_path=schedule_path,
                schedule_hash=schedule_hash,
                schedule_cell=cell,
                schedule_block_id=block,
                rate_limiter_override=shared_bucket,
                schedule_ordinals_override=ordinals[(dataset, cell)],
                schedule_block_query_ids_override=query_ids,
                config_snapshot={
                    **config,
                    "victim_profile_used": profile,
                    "generator_identity": generator.to_dict(),
                },
            )
            fingerprints.update(
                (manifest.get("provider_response_metadata") or {}).get(
                    "system_fingerprints", []
                )
            )
            first_call_at = (
                manifest.get("provider_response_metadata") or {}
            ).get("first_call_at")
            if first_call_at and not freeze_state_recorded:
                record_first_formal_call(
                    generator,
                    called_at=str(first_call_at),
                    state_root=config["paths"].get(
                        "generator_registry_state_dir",
                        "artifacts/v20/generator_registry_state",
                    ),
                )
                freeze_state_recorded = True
            if len(fingerprints) > 1:
                raise RuntimeError(
                    f"Provider fingerprint drift across matrix: {sorted(fingerprints)}"
                )
            done[(dataset, cell)].update(query_ids)
    print("[complete] frozen 90,000-request interleaved matrix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
