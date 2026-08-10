"""08：生成自然、多样且保持最小反事实不变量的实体槽核验问句。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.baselines.menta import (
    MENTA_NLI_MODEL_ID,
    MENTA_NLI_REVISION,
    TransformersNLIPredictor,
)
from src.llm.factory import (
    llm_profile_identity,
    load_llm_profiles,
    request_rate_limiter_from_profile,
    resolve_effective_llm_profile,
    resolve_llm_profile_name,
)
from src.llm.openai_compatible import OpenAICompatibleChatClient
from src.query_generation.diverse_slot_questions import (
    QUERY_TYPE,
    generate_diverse_paired_queries_file,
)
from src.query_generation.paired_query_builder import generate_paired_queries_file
from src.rag.embeddings import DEFAULT_EMBEDDING_MODEL, build_embedding_model
from src.utils.env import env_str
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析 Step 08 命令行参数。"""

    parser = argparse.ArgumentParser(
        description="Generate diverse entity-slotted PCV-MIA verification questions."
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"),
    )
    parser.add_argument(
        "--sibling-profile",
        default=None,
        help="Override the frozen sibling LLM profile for query naturalization.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def _build_metadata_chat_client(profile: dict[str, Any]) -> OpenAICompatibleChatClient:
    """从 effective sibling profile 构造可返回模型身份的客户端。"""

    if str(profile.get("provider") or "") != "openai_compatible":
        raise ValueError(
            "Diverse query generation requires an openai_compatible sibling profile"
        )
    extra_body = profile.get("extra_body") or {}
    if not isinstance(extra_body, dict):
        raise ValueError("Sibling profile extra_body must be a mapping")
    return OpenAICompatibleChatClient(
        base_url=str(profile.get("base_url") or ""),
        model=str(profile.get("model") or ""),
        api_key_env=str(profile.get("api_key_env") or "PCV_SIBLING_API_KEY"),
        system_prompt=str(profile.get("system_prompt") or ""),
        timeout=float(profile.get("timeout", 120.0)),
        max_retries=int(profile.get("max_retries", 0)),
        retry_backoff_base=float(profile.get("retry_backoff_base", 2.0)),
        retry_backoff_max=float(profile.get("retry_backoff_max", 30.0)),
        extra_body=dict(extra_body),
        stream=bool(profile.get("stream", False)),
        request_rate_limiter=request_rate_limiter_from_profile(profile),
    )


def _run_diverse_protocol(
    args: argparse.Namespace,
    config: dict[str, Any],
    query_cfg: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    """运行需要 sibling API、本地 NLI 与 embedding 的正式自然化协议。"""

    natural_cfg = query_cfg.get("naturalization") or {}
    nli_cfg = query_cfg.get("nli") or {}
    profiles = load_llm_profiles(config)
    profile_name = resolve_llm_profile_name(
        "sibling",
        cli_profile=args.sibling_profile,
        config_profile=query_cfg.get("sibling_profile"),
    )
    effective_profile = resolve_effective_llm_profile(
        profiles,
        "sibling",
        profile_name=profile_name,
    )
    profile_identity = llm_profile_identity(effective_profile)
    expected_model = str(effective_profile.get("model") or "").strip()
    frozen_model = str(env_str("PCV_SIBLING_MODEL") or "").strip()
    if not frozen_model or frozen_model != expected_model:
        raise ValueError(
            "PCV_SIBLING_MODEL must be explicitly frozen and match the effective profile "
            "before diverse Step 08 generation"
        )
    chat_client = _build_metadata_chat_client(effective_profile)

    nli_predictor = TransformersNLIPredictor(
        snapshot_dir=resolve_path(
            nli_cfg.get("snapshot_dir", "models/menta/deberta-base-long-nli")
        ),
        model_id=str(nli_cfg.get("model_id", MENTA_NLI_MODEL_ID)),
        revision=str(nli_cfg.get("revision", MENTA_NLI_REVISION)),
        device=str(nli_cfg.get("device", "cuda")),
        require_cuda=bool(nli_cfg.get("require_cuda", True)),
        batch_size=int(nli_cfg.get("batch_size", 16)),
        max_length=int(nli_cfg.get("max_length", 1280)),
    )
    nli_identity = {
        **dict(nli_predictor.identity),
        "device": str(nli_cfg.get("device", "cuda")),
        "require_cuda": bool(nli_cfg.get("require_cuda", True)),
        "max_length": int(nli_cfg.get("max_length", 1280)),
    }
    embedder = build_embedding_model(
        str(natural_cfg.get("embedding_model", DEFAULT_EMBEDDING_MODEL)),
        backend="auto",
        local_files_only=bool(natural_cfg.get("embedding_local_files_only", True)),
        revision=(
            str(natural_cfg["embedding_revision"])
            if natural_cfg.get("embedding_revision")
            else None
        ),
    )
    try:
        return generate_diverse_paired_queries_file(
            paired_claims_path=(
                resolve_path(config["paths"]["paired_claims_dir"])
                / f"{args.dataset}_paired_claims.jsonl"
            ),
            benchmark_path=(
                resolve_path(config["paths"]["benchmark_dir"])
                / f"{args.dataset}_attack_benchmark.jsonl"
            ),
            output_path=output_path,
            chat_client=chat_client,
            sibling_profile_identity=profile_identity,
            nli_predictor=nli_predictor,
            nli_identity=nli_identity,
            embedder=embedder,
            expected_provider_model_id=expected_model,
            pairs_per_source=int(query_cfg.get("pairs_per_source", 3)),
            candidates_per_pair=int(natural_cfg.get("candidates_per_pair", 3)),
            correction_retries=int(natural_cfg.get("correction_retries", 2)),
            temperature=float(natural_cfg.get("temperature", 0.2)),
            max_tokens=int(natural_cfg.get("max_tokens", 4096)),
            timeout=float(natural_cfg.get("timeout", effective_profile.get("timeout", 120.0))),
            min_question_proposition_similarity=float(
                natural_cfg.get("min_question_proposition_similarity", 0.80)
            ),
            max_five_gram_containment=float(
                natural_cfg.get("max_five_gram_containment", 0.35)
            ),
            max_longest_common_token_run=int(
                natural_cfg.get("max_longest_common_token_run", 8)
            ),
            max_dataset_duplicate_template_rate=float(
                natural_cfg.get("max_dataset_duplicate_template_rate", 0.01)
            ),
            max_dataset_opening_4gram_rate=float(
                natural_cfg.get("max_dataset_opening_4gram_rate", 0.15)
            ),
            resume=not args.no_resume,
            force=args.force,
        )
    finally:
        close_embedder = getattr(embedder, "close", None)
        if callable(close_embedder):
            close_embedder()


def main() -> int:
    """生成 Step 08 查询；正式配置默认走多样化实体槽协议。"""

    args = parse_args()
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging(
        "pcv_mia",
        log_file=resolve_path(config["logging"]["file"]),
        level=config["logging"].get("level", "INFO"),
    )
    query_cfg = config.get("paired_queries", {})
    query_types = [str(item) for item in query_cfg.get("query_types", [QUERY_TYPE])]
    out_dir = ensure_dir(resolve_path(config["paths"]["paired_queries_dir"]))
    output_path = out_dir / f"{args.dataset}_paired_queries.jsonl"
    if query_types == [QUERY_TYPE]:
        manifest = _run_diverse_protocol(args, config, query_cfg, output_path)
    else:
        # 仅供旧产物复现与 shadow 对照；正式矩阵不得混入旧查询类型。
        manifest = generate_paired_queries_file(
            paired_claims_path=(
                resolve_path(config["paths"]["paired_claims_dir"])
                / f"{args.dataset}_paired_claims.jsonl"
            ),
            output_path=output_path,
            query_types=query_types,
            resume=not args.no_resume,
            force=args.force,
        )
    logger.info("Step 08 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
