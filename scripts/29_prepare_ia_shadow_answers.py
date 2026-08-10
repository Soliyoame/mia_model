"""Freeze Luna IA queries and Qwen shadow answers before victim execution."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.baselines.ia_shadow import (
    build_dataset_manifest,
    load_source_bundle,
    prepare_source_bundle,
    write_source_bundle,
)
from src.baselines.representative import load_representative_targets
from src.llm.factory import (
    build_role_chat_client,
    llm_profile_identity,
    load_llm_profiles,
    resolve_llm_profile_name,
)
from src.rag.embeddings import build_embedding_model
from src.utils.io import load_yaml, resolve_path


QUERY_MODEL = "gpt-5.6-luna"
SHADOW_MODEL = "pcv-qwen3-4b:q4km-8k"
SHADOW_VERSION = "ollama:39297c75a309"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, choices=["edgar", "enron", "pubmed"])
    parser.add_argument("--baseline-config", default="configs/baseline_config_v21.yaml")
    parser.add_argument("--rag-config", default="configs/rag_config_v21.yaml")
    parser.add_argument("--luna-profile", default=None)
    parser.add_argument("--shadow-profile", default=None)
    parser.add_argument("--max-targets", type=int, default=None)
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args()


def _require_runtime() -> None:
    expected = Path(r"D:\python\anaconda\envs\mia_model\python.exe").resolve()
    if Path(sys.executable).resolve() != expected:
        raise RuntimeError(
            f"Wrong Python runtime: {sys.executable}; expected {expected}"
        )
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the frozen BGE relevance ranker")


def _require_identity(profile: dict, *, role: str, model: str, version: str | None) -> None:
    if str(profile.get("model") or "") != model:
        raise RuntimeError(f"{role} model drift: expected {model!r}")
    actual_version = str(profile.get("model_version") or "")
    if version is not None and actual_version != version:
        raise RuntimeError(f"{role} model version drift: expected {version!r}")
    if not actual_version:
        raise RuntimeError(f"{role} model version must be frozen before calls")


def main() -> int:
    args = parse_args()
    _require_runtime()
    baseline_config = load_yaml(args.baseline_config)
    rag_config = load_yaml(args.rag_config)
    profiles = load_llm_profiles(rag_config)

    luna_name = resolve_llm_profile_name(
        "sibling",
        cli_profile=args.luna_profile,
        config_profile="luna_query_generator",
    )
    shadow_name = resolve_llm_profile_name(
        "ia_shadow",
        cli_profile=args.shadow_profile,
        config_profile="qwen3_4b_ia_shadow",
    )
    luna, luna_profile = build_role_chat_client(
        profiles, "sibling", profile_name=luna_name
    )
    shadow, shadow_profile = build_role_chat_client(
        profiles, "ia_shadow", profile_name=shadow_name
    )
    _require_identity(luna_profile, role="Luna query generator", model=QUERY_MODEL, version=None)
    _require_identity(
        shadow_profile,
        role="Qwen IA shadow",
        model=SHADOW_MODEL,
        version=SHADOW_VERSION,
    )

    representative_path = (
        resolve_path(baseline_config["paths"]["representative_manifest_dir"])
        / f"{args.dataset}_representative_chunks.jsonl"
    )
    targets, _ = load_representative_targets(representative_path)
    if args.max_targets is not None:
        targets = targets[: max(0, int(args.max_targets))]
    elif len(targets) != 2000:
        raise RuntimeError(
            f"Formal IA requires exactly 2000 application targets/dataset, got {len(targets)}"
        )

    configured_root = baseline_config["paths"].get(
        "ia_shadow_answers_dir", "artifacts/v21/ia_shadow_answers"
    )
    output_root = resolve_path(args.output_dir or configured_root)
    if args.max_targets is not None and args.output_dir is None:
        raise ValueError("Diagnostic --max-targets requires an isolated --output-dir")

    embedding = rag_config["embedding"]
    ranker = build_embedding_model(
        embedding["model"],
        backend=embedding.get("backend", "auto"),
        local_files_only=bool(embedding.get("local_files_only", True)),
        revision=embedding.get("revision"),
        query_instruction=str(embedding.get("query_instruction") or ""),
    )

    def relevance_scores(questions: list[str], text: str) -> list[float]:
        query_vectors = np.asarray(ranker.encode_queries(questions), dtype="float32")
        document_vector = np.asarray(
            ranker.encode_documents([text])[0], dtype="float32"
        )
        return [float(np.dot(vector, document_vector)) for vector in query_vectors]

    def luna_call(prompt: str):
        return luna.chat_with_metadata(
            prompt,
            temperature=float(luna_profile.get("temperature", 0.0)),
            timeout=float(luna_profile.get("timeout", 120.0)),
            max_tokens=int(luna_profile.get("max_tokens", 2048)),
        )

    def shadow_call(prompt: str):
        return shadow.chat_with_metadata(
            prompt,
            temperature=0.0,
            timeout=float(shadow_profile.get("timeout", 180.0)),
            max_tokens=16,
        )

    for index, target in enumerate(targets, start=1):
        try:
            load_source_bundle(output_root, args.dataset, target)
            print(f"SKIP {index}/{len(targets)} {target.get('source_key')}", flush=True)
            continue
        except FileNotFoundError:
            pass
        bundle = prepare_source_bundle(
            target,
            dataset=args.dataset,
            query_call=luna_call,
            shadow_call=shadow_call,
            relevance_scores=relevance_scores,
            query_model_id=QUERY_MODEL,
            query_model_version=str(luna_profile["model_version"]),
            shadow_model_id=SHADOW_MODEL,
            shadow_model_version=SHADOW_VERSION,
        )
        write_source_bundle(bundle, output_root)
        if bundle["status"] != "ready":
            raise RuntimeError(
                f"IA shadow insufficient valid answers: {bundle['source_id']}"
            )
        print(f"READY {index}/{len(targets)} {bundle['source_id']}", flush=True)

    manifest = build_dataset_manifest(
        output_root,
        args.dataset,
        targets,
        query_identity=llm_profile_identity(luna_profile),
        shadow_identity=llm_profile_identity(shadow_profile),
    )
    print(
        f"FROZEN dataset={args.dataset} sources={manifest['source_count']} "
        f"query_hash={manifest['query_hash']} "
        f"shadow_hash={manifest['ia_shadow_manifest_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
