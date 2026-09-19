"""RAG 与 LLM-only 双模式运行模块。

中文说明
========
本文件对应流水线第 10 步，是 PCV-MIA 攻击的"实际开火"环节。它对每一个查询都跑
两遍，得到两种回答：
    1. RAG 模式：先去知识库检索相关文档，把检索到的内容塞进 prompt 再让大模型回答。
    2. LLM-only 模式：不给任何检索内容，只凭大模型自己的知识回答。
为什么要跑两遍：如果某文档真的在知识库里，RAG 模式因为能检索到它，回答会明显更
"懂"；而 LLM-only 模式回答不出来。两种模式的差异(后续打分阶段计算)就是判断
"该文档是否为成员"的核心信号。LLM-only 还能估计"模型自身知识造成的假阳性"。
- 名词：generator(生成器)=负责生成回答的大模型，这里就是被攻击的 victim 模型；
  prompt=喂给大模型的提示词；resume=断点续跑(已成功的查询不再重复请求)。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    # 进度条；没装 tqdm 就用"原样返回"的替身，不影响逻辑。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from .retriever import HybridRagRetriever, RagRetriever, RetrievedChunk
from .context_controls import GroundTruthContextController
from ..llm.response_validation import (
    generator_response_error,
    response_record_is_success,
)
from ..llm.victim_client import VictimClient
from ..utils.hash import sha256_file, sha256_obj, sha256_text
from ..utils.io import ensure_dir, load_yaml, read_json, read_jsonl, write_json, write_jsonl, write_jsonl_atomic
from ..utils.logger import get_logger
from ..utils.rate_limit import TokenBucket
from ..utils.run_context import git_snapshot, require_clean_release_commit


LOGGER = get_logger(__name__)

PCV_RUNTIME_PROMPT_VERSION = "pcv-single-query-blackbox-v1"
PCV_ATTACK_REQUEST_TEMPLATE = (
    "{query}\n\n"
    'Answer exactly one line: "Consistent", '
    '"Inconsistent: <correct value>", or "I don\'t know".'
)
PCV_RAG_SHELL_TEMPLATE = (
    "You are a helpful assistant.\n"
    "Use the reference information to answer the user's request.\n\n"
    "Reference information:\n{contexts}\n\n"
    "User request:\n{query}"
)
PCV_LLM_ONLY_SHELL_TEMPLATE = (
    "Answer the user's request using your own knowledge.\n\n"
    "User request:\n{query}"
)
PCV_ATTACK_REQUEST_PROMPT_HASH = sha256_text(PCV_ATTACK_REQUEST_TEMPLATE)
PCV_RUNTIME_PROMPT_HASH = sha256_obj({
    "attack_request_template": PCV_ATTACK_REQUEST_TEMPLATE,
    "rag_shell_template": PCV_RAG_SHELL_TEMPLATE,
    "llm_only_shell_template": PCV_LLM_ONLY_SHELL_TEMPLATE,
})


def build_pcv_attack_request(query: str) -> str:
    """把原始 Q+/Q- 包成 attacker-controlled 的回答格式要求。"""
    return PCV_ATTACK_REQUEST_TEMPLATE.format(query=query)


def is_retryable_generator_error(exc: Exception) -> bool:
    """识别需要长冷却后继续重试的模型 API/网络错误。"""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    message = str(exc).lower()
    markers = (
        "empty_response",
        "timed out",
        "timeout",
        "urlopen error",
        "connection reset",
        "connection aborted",
        "connection refused",
        "remote end closed",
        "unexpected_eof",
        "eof occurred",
        "temporarily unavailable",
        "http 408",
        "http 425",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "http 520",
        "http 522",
        "http 524",
        '"code": 429',
        "rate limit",
        "resource_exhausted",
    )
    return any(marker in message for marker in markers)


def response_is_success(row: dict[str, Any]) -> bool:
    """统一检查错误文本、显式 error 和 provider 实际模型身份。"""
    return response_record_is_success(row)


def compact_response_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """按 query_id 成功优先压实；同为成功或失败时保留最后一条。"""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        query_id = str(row.get("query_id") or "")
        if not query_id:
            continue
        previous = best.get(query_id)
        if previous is None or response_is_success(row) or not response_is_success(previous):
            best[query_id] = row
    compacted = [best[key] for key in sorted(best)]
    succeeded = sum(1 for row in compacted if response_is_success(row))
    return compacted, {
        "input_rows": len(rows),
        "unique_queries": len(compacted),
        "duplicates_removed": max(0, len(rows) - len(compacted)),
        "succeeded": succeeded,
        "failed": len(compacted) - succeeded,
    }


def compact_response_file(path: str | Path) -> dict[str, int]:
    """压实一个响应 JSONL，并用原子替换避免留下半截文件。"""
    p = Path(path)
    rows = list(read_jsonl(p)) if p.exists() else []
    compacted, stats = compact_response_rows(rows)
    if rows:
        write_jsonl_atomic(compacted, p)
    return stats


def validate_fixed_query_budget(
    query_rows: list[dict[str, Any]],
    pairs_per_source: int,
    *,
    expected_source_keys: set[str] | None = None,
    allow_shared_q_plus: bool = False,
) -> dict[str, Any]:
    """Fail closed unless every source has exactly N complete Q+/Q- pairs."""

    required = int(pairs_per_source)
    if required < 1:
        raise ValueError("pairs_per_source must be a positive integer")
    query_ids: set[str] = set()
    by_source: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in query_rows:
        query_id = str(row.get("query_id") or "")
        if not query_id or query_id in query_ids:
            raise RuntimeError(f"Fixed-budget plan has missing/duplicate query_id: {query_id!r}")
        query_ids.add(query_id)
        source_key = str(row.get("source_key") or row.get("source_id") or "")
        if not source_key:
            raise RuntimeError(f"Fixed-budget query is missing source_key: {query_id}")
        pair_key = f"{row.get('pair_id')}::{row.get('query_type') or 'default'}"
        by_source.setdefault(source_key, {}).setdefault(pair_key, []).append(row)

    failures: list[str] = []
    if not by_source:
        failures.append("no_sources")
    actual_source_keys = set(by_source)
    if expected_source_keys is not None:
        missing = sorted(expected_source_keys - actual_source_keys)
        unexpected = sorted(actual_source_keys - expected_source_keys)
        if missing:
            failures.append(f"missing_sources={missing[:10]} (total={len(missing)})")
        if unexpected:
            failures.append(f"unexpected_sources={unexpected[:10]} (total={len(unexpected)})")
    for source_key, pairs in sorted(by_source.items()):
        if len(pairs) != required:
            failures.append(f"{source_key}:pairs={len(pairs)}")
            continue
        query_texts = [str(member.get("query") or "") for members in pairs.values() for member in members]
        if any(not query for query in query_texts):
            failures.append(f"{source_key}:empty_query_text")
        elif not allow_shared_q_plus and len(set(query_texts)) != required * 2:
            failures.append(f"{source_key}:duplicate_query_text")
        if allow_shared_q_plus:
            plus_texts = {member["query"] for members in pairs.values() for member in members
                          if member.get("claim_type") == "true"}
            minus_texts = [member["query"] for members in pairs.values() for member in members
                           if member.get("claim_type") == "counterfactual"]
            if len(set(minus_texts)) != required or plus_texts.intersection(minus_texts):
                failures.append(f"{source_key}:duplicate_counterfactual_query_text")
        for pair_key, members in pairs.items():
            claim_types = sorted(str(member.get("claim_type")) for member in members)
            if claim_types != ["counterfactual", "true"]:
                failures.append(f"{source_key}:{pair_key}:claim_types={claim_types}")
    if failures:
        preview = "; ".join(failures[:10])
        raise RuntimeError(
            f"Fixed query budget violation (required {required} pairs/{required * 2} queries per source): {preview}"
        )
    source_keys = sorted(actual_source_keys)
    return {
        "pairs_per_source": required,
        "queries_per_source": required * 2,
        "source_count": len(source_keys),
        "planned_queries": len(query_ids),
        "source_plan_hash": sha256_obj(source_keys),
        "query_plan_hash": sha256_obj(sorted(query_ids)),
    }


def _validate_v24_main_index(
    index_dir: Path, *, dataset: str, backend: str,
    expected_manifest_hash: str, member_hashes: dict[str, str],
) -> dict[str, Any]:
    """在加载模型前核对已有索引文件与主库 source 边界，不重建索引。"""
    manifest_path = index_dir / "index_manifest.json"
    manifest = read_json(manifest_path)
    if (not expected_manifest_hash or sha256_file(manifest_path) != expected_manifest_hash
            or manifest.get("dataset") != dataset or manifest.get("retriever_backend") != backend):
        raise ValueError("v24_index_identity_mismatch")
    boundary = manifest.get("security_boundary") or {}
    if boundary.get("allowed_groups") != ["KB_Member"] or boundary.get("is_shadow_index") is not False:
        raise ValueError("v24_index_not_main_member_only")
    if backend == "dense" and (not manifest.get("embedding_revision")
                               or manifest.get("embedding_local_files_only") is not True):
        raise ValueError("v24_index_requires_fixed_local_embedding")
    docstore_path = index_dir / "docstore.jsonl"
    index_path = (index_dir / str(manifest.get("index_filename") or "")).resolve()
    if not index_path.is_relative_to(index_dir.resolve()):
        raise ValueError("v24_index_path_outside_directory")
    if (sha256_file(docstore_path) != manifest.get("docstore_hash")
            or sha256_file(index_path) != manifest.get("index_hash")):
        raise ValueError("v24_index_content_hash_mismatch")
    seen: set[str] = set()
    chunk_ids: set[str] = set()
    for row in read_jsonl(docstore_path):
        key, chunk_id = row.get("source_key"), row.get("chunk_id")
        metadata = row.get("metadata") or {}
        if (row.get("dataset") != dataset or row.get("group") != "KB_Member"
                or key not in member_hashes or metadata.get("source_key") != key
                or metadata.get("source_text_hash") != member_hashes[key]):
            raise ValueError("v24_index_split_source_mismatch")
        if (not chunk_id or chunk_id in chunk_ids or not isinstance(row.get("text"), str)
                or sha256_text(row["text"]) != row.get("text_hash")):
            raise ValueError("v24_index_chunk_identity_mismatch")
        seen.add(key)
        chunk_ids.add(chunk_id)
    if seen != set(member_hashes):
        raise ValueError("v24_index_member_coverage_mismatch")
    return manifest


def run_v24_formal_cell(
    *, dataset: str, config_path: str | Path, project_root: str | Path = ".",
    dry_run: bool = False, resume: bool = True,
) -> dict[str, Any]:
    """显式 V24 主 cell：固定 pairs/split/index → 现有 RAG 循环 → hybrid PVS。"""
    from ..llm.factory import build_victim_client, llm_profile_identity, resolve_effective_llm_profile
    from ..prepare.restoration_first_v24 import GROUP_COUNTS, build_luna_direct_run_plan
    from ..scoring.pcv_scorer import (
        build_hybrid_pvs_nli, prepare_hybrid_pvs_inputs,
        run_hybrid_pvs_scoring, validate_hybrid_pvs_config,
    )
    from ..utils.seed import set_seed

    root = Path(project_root).resolve()
    config_file = (root / config_path).resolve()
    config = load_yaml(config_file)
    if config.get("protocol_version") != "pcv-mia-v24" or dataset not in config.get("datasets", []):
        raise ValueError("v24_formal_config_required")
    formal = config.get("formal") or {}
    if (config.get("eligibility", {}).get("target_sources") != 2250
            or config.get("split", {}).get("counts") != GROUP_COUNTS
            or formal.get("queries_per_source") != 6
            or formal.get("victim_queries_per_dataset") != 12000
            or formal.get("reserve_in_main_victim_budget") is not False):
        raise ValueError("v24_formal_budget_or_split_drift")
    validate_hybrid_pvs_config(config, root)
    runtime = formal.get("runtime")
    required = ("selected_pairs_path", "split_manifest_path", "output_dir", "llm_profiles_path",
                "victim_profile", "generator_family", "concrete_model", "generator_version")
    if not isinstance(runtime, dict) or any(
        not isinstance(runtime.get(key), str) or not runtime[key].strip() for key in required
    ):
        raise ValueError("v24_formal_runtime_bindings_required")
    retrieval, generation = runtime.get("retrieval") or {}, runtime.get("generation") or {}
    backend = retrieval.get("backend")
    if (backend not in {"dense", "bm25", "hybrid"} or not retrieval.get("retriever_id")
            or not retrieval.get("index_dir") or not retrieval.get("index_manifest_sha256")
            or not isinstance(retrieval.get("top_k"), int) or retrieval["top_k"] < 1):
        raise ValueError("v24_formal_retriever_bindings_required")
    generation_keys = {"temperature", "max_tokens", "timeout", "retries", "retry_backoff_base",
                       "retry_backoff_max", "retry_until_success", "retry_cooldown_seconds",
                       "request_interval_seconds", "max_workers", "requests_per_minute", "checkpoint_every"}
    if (not isinstance(generation, dict) or set(generation) != generation_keys
            or generation["max_tokens"] < 1 or generation["max_workers"] < 1
            or generation["timeout"] <= 0 or generation["checkpoint_every"] < 1):
        raise ValueError("v24_formal_generation_config_required")
    pairs_path = (root / runtime["selected_pairs_path"]).resolve()
    split_path = (root / runtime["split_manifest_path"]).resolve()
    output = (root / runtime["output_dir"]).resolve()
    split = read_json(split_path)
    if split.get("selection_seed") != config.get("selection_seed"):
        raise ValueError("v24_formal_split_seed_mismatch")
    plan = build_luna_direct_run_plan(list(read_jsonl(pairs_path)), split, dataset=dataset)
    budget = validate_fixed_query_budget(
        plan["queries"], 3, expected_source_keys={row["source_key"] for row in plan["benchmark"]},
        allow_shared_q_plus=True,
    )
    member_hashes = {row["source_key"]: row["source_hash"] for row in split["rows"] if row["group"] == "KB_Member"}
    index_dir = (root / retrieval["index_dir"]).resolve()
    index_manifest = _validate_v24_main_index(
        index_dir, dataset=dataset, backend="dense" if backend == "hybrid" else backend,
        expected_manifest_hash=retrieval["index_manifest_sha256"], member_hashes=member_hashes,
    )
    hybrid = retrieval.get("hybrid") or {}
    bm25_dir = None
    if backend == "hybrid":
        if (not retrieval.get("bm25_index_dir") or not retrieval.get("bm25_index_manifest_sha256")
                or not hybrid.get("reranker_revision") or hybrid.get("reranker_local_files_only") is not True
                or hybrid.get("final_top_k") != retrieval["top_k"]):
            raise ValueError("v24_formal_hybrid_bindings_required")
        bm25_dir = (root / retrieval["bm25_index_dir"]).resolve()
        sparse = _validate_v24_main_index(
            bm25_dir, dataset=dataset, backend="bm25",
            expected_manifest_hash=retrieval["bm25_index_manifest_sha256"], member_hashes=member_hashes,
        )
        if sparse["docstore_hash"] != index_manifest["docstore_hash"]:
            raise ValueError("v24_formal_hybrid_docstore_mismatch")
        expected_retriever_id = f"{index_manifest['retriever_id']}+bm25+rrf+bge-reranker"
    else:
        expected_retriever_id = index_manifest.get("retriever_id")
    if retrieval["retriever_id"] != expected_retriever_id:
        raise ValueError("v24_formal_retriever_id_mismatch")
    profiles_path = root / runtime["llm_profiles_path"]
    profiles = load_yaml(profiles_path)
    profile = resolve_effective_llm_profile(profiles, "victim", profile_name=runtime["victim_profile"])
    if (profile.get("model") != runtime["concrete_model"]
            or profile.get("model_version") != runtime["generator_version"]):
        raise ValueError("v24_formal_generator_identity_mismatch")
    profile_hash = llm_profile_identity(profile)["profile_hash"]
    git = git_snapshot()
    cell = {key: runtime[key] for key in ("generator_family", "concrete_model", "generator_version")}
    cell.update(mode="rag", variant_id="full_pvs", context_control="retrieved",
                retriever_backend=backend, retriever_id=retrieval["retriever_id"])
    binding = {
        "protocol_version": "pcv-mia-v24", "run_role": "main", "cell": cell,
        "config_sha256": sha256_file(config_file), "selected_pairs_sha256": sha256_file(pairs_path),
        "split_sha256": sha256_file(split_path), "profile_sha256": profile_hash,
        "profiles_sha256": sha256_file(profiles_path),
        "runtime_prompt_version": PCV_RUNTIME_PROMPT_VERSION,
        "attack_request_prompt_hash": PCV_ATTACK_REQUEST_PROMPT_HASH,
        "runtime_prompt_hash": PCV_RUNTIME_PROMPT_HASH,
        "code_commit": git.get("commit"), "selection_seed": config["selection_seed"],
        "allow_shared_q_plus": True,
    }
    summary = {
        "run_kind": "v24_formal_cell", "status": "prepared_inputs_only", "binding": binding,
        "split": plan["split"], "fixed_budget": budget, "planned_victim_queries": len(plan["queries"]),
        "reserve_victim_queries": 0, "git": git, "artifacts": {},
    }
    if dry_run:
        return summary
    code_commit = require_clean_release_commit(git)
    summary_path, raw_path = output / "run_summary.json", output / "rag_responses.jsonl"
    exports = {"selected_main_pairs.jsonl": plan["pairs"], "query_plan.jsonl": plan["queries"],
               "benchmark.jsonl": plan["benchmark"]}
    if output.exists():
        if not resume or not summary_path.is_file():
            raise FileExistsError("v24_formal_output_exists_use_resume_or_new_directory")
        previous = read_json(summary_path)
        if previous.get("binding") != binding:
            raise ValueError("v24_formal_resume_binding_drift")
        for name, expected_hash in previous["artifacts"].items():
            if sha256_file(output / name) != expected_hash:
                raise ValueError("v24_formal_resume_artifact_drift")
        for name, rows in exports.items():
            if list(read_jsonl(output / name)) != rows:
                raise ValueError("v24_formal_resume_plan_drift")
        if previous["status"] == "completed":
            return {**previous, "resumed_completed": True}
        summary = previous

    def bound_responses() -> list[dict[str, Any]]:
        rows = compact_response_rows(list(read_jsonl(raw_path)))[0] if raw_path.exists() else []
        prepare_hybrid_pvs_inputs(plan["pairs"], rows, dataset=dataset)
        for row in rows:
            if any(row.get(key) != value for key, value in cell.items()):
                raise ValueError("v24_formal_response_cell_drift")
        if raw_path.exists():
            identity = read_json(raw_path.with_suffix(".identity.json"))
            if (identity.get("execution_binding") != binding or identity.get("allow_shared_q_plus") is not True
                    or identity.get("query_hash") != sha256_file(output / "query_plan.jsonl")
                    or identity.get("benchmark_hash") != sha256_file(output / "benchmark.jsonl")):
                raise ValueError("v24_formal_response_identity_drift")
        return rows

    rows = bound_responses()
    pending = len(plan["queries"]) - sum(response_is_success(row) for row in rows)
    score_dir = output / "scores"
    # 恢复已写完的评分时只核对输入和输出 hash，不重复调用模型。
    if score_dir.exists():
        scored = read_json(score_dir / "scoring_summary.json")
        if (pending or scored.get("run_kind") != "v24_formal_hybrid_pvs"
                or scored.get("config_sha256") != binding["config_sha256"]
                or scored.get("pairs_sha256") != sha256_file(output / "selected_main_pairs.jsonl")
                or scored.get("responses_sha256") != sha256_file(raw_path)):
            raise ValueError("v24_formal_scoring_resume_drift")
        for name in ("pair_scores", "source_scores"):
            if sha256_file(score_dir / f"{name}.jsonl") != scored.get(f"{name}_sha256"):
                raise ValueError("v24_formal_scoring_output_drift")
    else:
        # 固定 NLI 在第一次 victim 调用前加载，缺权重/CUDA 时不会先花费查询预算。
        nli = build_hybrid_pvs_nli(config, root)
        if pending:
            set_seed(int(config["selection_seed"]))
            retriever = (HybridRagRetriever(index_dir, bm25_dir, **hybrid)
                         if backend == "hybrid" else RagRetriever(index_dir))
            if (retriever.retriever_backend != backend
                    or retriever.manifest.get("retriever_id") != retrieval["retriever_id"]):
                raise ValueError("v24_formal_loaded_retriever_drift")
            client, loaded_profile = build_victim_client(profiles, profile_name=runtime["victim_profile"])
            if llm_profile_identity(loaded_profile)["profile_hash"] != profile_hash:
                raise ValueError("v24_formal_loaded_profile_drift")
            if not output.exists():
                output.mkdir(parents=True, exist_ok=False)
                for name, content in exports.items():
                    write_jsonl(content, output / name)
                summary["artifacts"] = {name: sha256_file(output / name) for name in exports}
            summary["status"] = "running"
            write_json(summary, summary_path)
            run_rag_and_llm_only(
                dataset=dataset, queries_path=output / "query_plan.jsonl", benchmark_path=output / "benchmark.jsonl",
                index_dir=index_dir, rag_output_path=raw_path, llm_output_path=output / "unused_llm_only.jsonl",
                client=client, top_k=retrieval["top_k"], **generation,
                resume=resume, force=False, config_snapshot={"v24_binding": binding},
                run_rag=True, run_llm_only=False, pairs_per_source=3, allow_shared_q_plus=True,
                generator_id=runtime["concrete_model"], generator_version=runtime["generator_version"],
                generator_family=runtime["generator_family"], concrete_model=runtime["concrete_model"],
                code_commit=code_commit, retriever_override=retriever,
                retriever_identity_override=retrieval["retriever_id"], execution_binding=binding,
            )
            rows = bound_responses()
        succeeded = sum(response_is_success(row) for row in rows)
        summary.update(response_count=len(rows), succeeded_queries=succeeded,
                       missing_or_failed_queries=len(plan["queries"]) - succeeded)
        if succeeded != len(plan["queries"]):
            summary["status"] = "rag_incomplete"
            write_json(summary, summary_path)
            return summary
        scored = run_hybrid_pvs_scoring(
            dataset=dataset, config_path=config_file, pairs_path=output / "selected_main_pairs.jsonl",
            responses_path=raw_path, output_dir=score_dir, project_root=root, run_role="formal", nli=nli,
        )
    summary.update(status="completed" if scored["status"] == "scored" else "scoring_incomplete",
                   scoring_status=scored["status"], scored_pair_count=scored["scored_pair_count"],
                   scored_source_count=scored["scored_source_count"])
    for path in (raw_path, raw_path.with_suffix(".identity.json"), raw_path.with_suffix(".manifest.json"),
                 score_dir / "pair_scores.jsonl", score_dir / "source_scores.jsonl", score_dir / "scoring_summary.json"):
        summary["artifacts"][path.relative_to(output).as_posix()] = sha256_file(path)
    write_json(summary, summary_path)
    return summary


def build_rag_prompt(query: str, contexts: list[str]) -> str:
    """通用 RAG shell；query 接收已包装的 attacker request，不内置回答格式。"""
    # 用分隔线把多个检索片段连起来，让模型能区分不同来源。
    joined = "\n\n---\n\n".join(contexts)
    return PCV_RAG_SHELL_TEMPLATE.format(contexts=joined, query=query)


def build_llm_only_prompt(query: str) -> str:
    """无检索的通用 shell；query 接收与 RAG 相同的 attacker request。"""
    return PCV_LLM_ONLY_SHELL_TEMPLATE.format(query=query)


def _make_llm_row(
    query_row: dict[str, Any],
    response: str,
    error: str | None,
    *,
    dataset: str,
    temperature: float,
    max_tokens: int,
    created_at: str,
    variant_id: str,
) -> dict[str, Any]:
    """构造一条 LLM-only 结果行。

    单发路与批处理路共用本工厂,确保两条路写出的字段结构【逐字段一致】——批处理只是
    换了"如何拿到 response 文本",落盘格式与下游 stance 解析看到的内容与单发无任何差异。
    """
    query_id = str(query_row["query_id"])
    return {
        "request_id": f"llm_req_{query_id}",
        "mode": "llm_only",
        "variant_id": variant_id,
        "query_id": query_id,
        "pair_id": query_row.get("pair_id"),
        "fact_id": query_row.get("fact_id"),
        "audit_id": query_row["audit_id"],
        "doc_id": query_row.get("doc_id"),
        "source_id": query_row.get("source_id") or query_row.get("doc_id"),
        "source_key": query_row.get("source_key") or query_row.get("source_id") or query_row.get("doc_id"),
        "claim_type": query_row.get("claim_type"),
        "dataset": dataset,
        "group": query_row["group"],
        "query": str(query_row["query"]),
        "expected_entity": query_row.get("expected_entity") or query_row.get("original_entity"),
        "counterfactual_entity": query_row.get("counterfactual_entity") or query_row.get("conflict_entity"),
        "entity_type": query_row.get("entity_type"),
        "response": response,
        "generation_config": {"temperature": temperature, "max_tokens": max_tokens},
        "error": error,
        "created_at": created_at,
    }


def run_rag_and_llm_only(
    dataset: str,
    queries_path: str | Path,
    benchmark_path: str | Path,
    index_dir: str | Path,
    rag_output_path: str | Path,
    llm_output_path: str | Path,
    client: VictimClient | None = None,
    top_k: int = 5,
    temperature: float = 0.0,
    max_tokens: int = 512,
    timeout: float = 60.0,
    retries: int = 2,
    retry_backoff_base: float = 2.0,
    retry_backoff_max: float = 60.0,
    retry_until_success: bool = True,
    retry_cooldown_seconds: float = 300.0,
    request_interval_seconds: float = 0.0,
    max_workers: int = 1,
    resume: bool = True,
    force: bool = False,
    config_snapshot: dict[str, Any] | None = None,
    run_rag: bool = True,
    run_llm_only: bool = False,
    allowed_fact_ids: set[str] | None = None,
    requests_per_minute: float = 0.0,
    variant_id: str = "full_pvs",
    checkpoint_every: int = 200,
    pairs_per_source: int | None = None,
    generator_id: str | None = None,
    generator_version: str | None = None,
    generator_family: str | None = None,
    concrete_model: str | None = None,
    code_commit: str | None = None,
    retriever_override: Any | None = None,
    context_control: str = "retrieved",
    retriever_identity_override: str | None = None,
    ground_truth_source_store_path: str | Path | None = None,
    schedule_path: str | Path | None = None,
    schedule_hash: str | None = None,
    schedule_cell: str | None = None,
    schedule_block_id: str | None = None,
    rate_limiter_override: Any | None = None,
    schedule_ordinals_override: dict[str, int] | None = None,
    schedule_block_query_ids_override: set[str] | None = None,
    allow_shared_q_plus: bool = False,
    execution_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对 accepted query 同时运行 RAG 和 LLM-only。

    中文说明：本函数是第 10 步主入口。它读入所有"通过筛选(accepted)"的查询，对每条
    查询分别跑 RAG 和 LLM-only，把两边的回答各自写到一个 jsonl 文件，最后写一份
    manifest。支持断点续跑、失败重试、限速和多线程并发。

    参数:
        dataset:                 数据集名。
        queries_path:            查询文件(jsonl)路径，每行一个查询。
        benchmark_path:          攻击基准文件路径，用来查每条查询对应的目标文档 id。
        index_dir:               RAG 索引目录(供检索器加载)。
        rag_output_path:         RAG 模式回答的输出文件。
        llm_output_path:         LLM-only 模式回答的输出文件。
        client:                  调用大模型的客户端(VictimClient)，必须提供。
        top_k:                   每条查询检索多少个文档片段。
        temperature:             采样温度，0 表示尽量确定性输出(利于复现)。
        max_tokens:              单次回答最多生成多少 token。
        timeout:                 单次请求超时秒数。
        retries:                 失败后最多重试几次。
        retry_backoff_base:      重试退避的基数(指数退避)。
        retry_backoff_max:       重试退避的上限秒数。
        retry_until_success:     API/网络错误在短重试耗尽后是否长冷却并继续重试到成功。
        retry_cooldown_seconds:  每轮短重试耗尽后的长冷却秒数。
        request_interval_seconds:每次请求之间的固定间隔(限速，防止把 API 打挂)。
        max_workers:             并发线程数，>1 时多条查询并行处理。
        resume:                  断点续跑：跳过已成功的查询。
        force:                   强制重跑：忽略已有结果。
        config_snapshot:         配置快照，写进 manifest 便于复现。
        run_rag:                 是否跑 RAG 路。matched-control 只采集 LLM-only 时传 False。
        run_llm_only:            是否跑 LLM-only 路。L2 shadow 推理只需要 RAG 路
                                 (LLM-only 与索引无关、跨 shadow 不变，复用主 run 即可)，
                                 此时传 False 可省掉 K 倍 LLM-only 调用。
        allowed_fact_ids:        若非 None,只处理 fact_id 在该集合内的 query(primary-only 砍量),
                                 同时减少 RAG 与 LLM-only 两路调用数,不引入任何伪影。
        requests_per_minute:     >0 时启用【全局令牌桶】限速(替代 per-call 固定 sleep)：全局速率恒
                                 ≤ 此 RPM,但配合 max_workers>1,某条 call 卡住时别的线程仍能发满 RPM,
                                 抗端点间歇卡顿(实测卡顿会把每条均摊到 ~72–96s,远超 4RPM 的 15s 地板)。
                                 =0(默认)沿用旧行为(每条 call 后固定 sleep request_interval_seconds)。
        checkpoint_every:        累积多少条响应后写盘；必须为正整数，默认 200。
    返回:
        manifest(字典)：本次运行的统计与路径信息。
    异常:
        ValueError: 未提供 client 时抛出。
    """
    # 没有大模型客户端就没法生成回答，直接报错。
    if client is None:
        raise ValueError("run_rag_and_llm_only requires a configured VictimClient.")
    if not run_rag and not run_llm_only:
        raise ValueError("At least one of run_rag or run_llm_only must be enabled.")
    if checkpoint_every < 1:
        raise ValueError("checkpoint_every must be a positive integer.")
    variant = str(variant_id or "").strip()
    if not variant:
        raise ValueError("variant_id must be non-empty")
    normalized_context_control = str(context_control or "retrieved").casefold()
    if normalized_context_control not in {"retrieved", "oracle", "random"}:
        raise ValueError(f"Unknown context_control: {context_control!r}")
    if normalized_context_control != "retrieved" and ground_truth_source_store_path is None:
        raise ValueError(
            "Oracle/Random controls require ground_truth_source_store_path"
        )
    if schedule_path is not None:
        actual_schedule_hash = sha256_file(schedule_path)
        if schedule_hash and actual_schedule_hash != schedule_hash:
            raise RuntimeError("Execution schedule hash mismatch")
        schedule_hash = actual_schedule_hash
    rag_output = Path(rag_output_path)
    llm_output = Path(llm_output_path)
    # API 调用前加载 Retriever，并冻结 resume 所需的完整实验身份。
    retriever = None
    if run_rag:
        retriever = retriever_override or RagRetriever(index_dir)
    context_controller = None
    if run_rag and normalized_context_control != "retrieved":
        base_retriever = getattr(retriever, "dense", retriever)
        context_controller = GroundTruthContextController(
            source_store_path=ground_truth_source_store_path,
            dense_retriever=base_retriever,
        )
    index_manifest_path = Path(index_dir) / "index_manifest.json"
    index_manifest_hash = None
    if retriever is not None:
        index_manifest_hash = getattr(retriever, "index_manifest_hash", None)
        if not index_manifest_hash:
            index_manifest_hash = (
                sha256_file(index_manifest_path)
                if index_manifest_path.is_file()
                else sha256_obj(getattr(retriever, "manifest", {}))
            )
    effective_model = str(concrete_model or generator_id or "").strip()
    resume_identity = {
        "dataset": dataset,
        "generator_family": str(generator_family or "").strip().casefold(),
        "concrete_model": effective_model,
        "generator_version": str(generator_version or "").strip(),
        "retriever_id": (
            str(
                retriever_identity_override
                or getattr(retriever, "manifest", {}).get("retriever_id")
                or ""
            )
            if retriever is not None
            else "none"
        ),
        "retriever_manifest": (
            getattr(retriever, "manifest", {}) if retriever is not None else None
        ),
        "index_manifest_hash": index_manifest_hash,
        "query_hash": sha256_file(queries_path),
        "benchmark_hash": sha256_file(benchmark_path),
        "runtime_prompt_version": PCV_RUNTIME_PROMPT_VERSION,
        "attack_request_prompt_hash": PCV_ATTACK_REQUEST_PROMPT_HASH,
        "runtime_prompt_hash": PCV_RUNTIME_PROMPT_HASH,
        "code_commit": str(
            code_commit
            or (
                git_snapshot().get("commit")
                if generator_family and effective_model
                else ""
            )
            or ""
        ),
        "ground_truth_source_store_hash": (
            sha256_file(ground_truth_source_store_path)
            if ground_truth_source_store_path is not None
            else None
        ),
        "schedule_hash": str(schedule_hash or ""),
        "schedule_cell": str(schedule_cell or ""),
    }
    # 只在显式新入口记录扩展绑定，历史运行身份保持原样。
    if allow_shared_q_plus:
        resume_identity["allow_shared_q_plus"] = True
    if execution_binding is not None:
        resume_identity["execution_binding"] = execution_binding
    identity_targets: list[tuple[Path, Path]] = []
    if run_rag:
        identity_targets.append(
            (rag_output.with_suffix(".identity.json"), rag_output)
        )
    if run_llm_only:
        identity_targets.append(
            (llm_output.with_suffix(".identity.json"), llm_output)
        )
    for identity_path, response_path in identity_targets:
        if identity_path.exists():
            existing_identity = read_json(identity_path)
            if existing_identity != resume_identity:
                raise RuntimeError(
                    f"Experiment identity mismatch for {identity_path}: "
                    f"expected={resume_identity}, actual={existing_identity}"
                )
        elif response_path.exists():
            raise RuntimeError(
                f"Refusing identity-free overwrite/resume for existing response file: {response_path}"
            )
        ensure_dir(identity_path.parent)
        write_json(resume_identity, identity_path)
    # done_rag / done_llm：已经成功跑完的查询 id 集合(用于跳过)。
    done_rag = set()
    done_llm = set()
    # append_*：输出文件已存在时改为"追加写"，避免覆盖之前的结果。
    append_rag = False
    append_llm = False
    if resume and not force:
        # 续跑模式下，先扫描已有输出，记下哪些查询已经成功完成。
        if run_rag:
            compact_response_file(rag_output)
        if run_llm_only:
            compact_response_file(llm_output)
        done_rag = _successful_query_ids(rag_output) if run_rag else set()
        done_llm = _successful_query_ids(llm_output) if run_llm_only else set()
        append_rag = run_rag and rag_output.exists()
        append_llm = run_llm_only and llm_output.exists()
    existing_fingerprints: set[str] = set()
    for response_path, enabled in (
        (rag_output, run_rag),
        (llm_output, run_llm_only),
    ):
        if enabled and response_path.is_file():
            existing_fingerprints.update(
                str(row["system_fingerprint"])
                for row in read_jsonl(response_path)
                if response_is_success(row) and row.get("system_fingerprint")
            )
    if len(existing_fingerprints) > 1:
        raise RuntimeError(
            f"Provider system fingerprint drift in existing suite: "
            f"{sorted(existing_fingerprints)}"
        )
    fingerprint_state = {
        "value": next(iter(existing_fingerprints), None)
    }
    fingerprint_lock = threading.Lock()

    def validate_fingerprint(metadata: dict[str, Any]) -> None:
        value = metadata.get("system_fingerprint")
        if value is None:
            return
        fingerprint = str(value)
        with fingerprint_lock:
            if fingerprint_state["value"] is None:
                fingerprint_state["value"] = fingerprint
            elif fingerprint_state["value"] != fingerprint:
                raise RuntimeError(
                    "Provider system fingerprint drift: "
                    f"{fingerprint_state['value']} -> {fingerprint}"
                )

    # 把基准文件读成"audit_id → 整行"的字典，便于按 id 快速查目标文档。
    benchmark = {row["audit_id"]: row for row in read_jsonl(benchmark_path)}
    benchmark_source_keys = {
        str(row.get("source_key") or row.get("source_id") or row.get("audit_id"))
        for row in benchmark.values()
    }
    # matched LLM-only 对照不触碰检索器。
    created_at = datetime.now(timezone.utc).isoformat()

    # 限速方式二选一：
    #   · requests_per_minute > 0 → 用【全局令牌桶】限速(抗卡顿)：发请求前 acquire() 取令牌，
    #     全局速率恒 ≤ RPM；配合 max_workers>1，某条 call 卡住时别的线程仍能发满 RPM。
    #     此时不再用 per-call 固定 sleep(令牌桶已负责匀速)。
    #   · requests_per_minute <= 0 (默认) → 沿用旧行为：每条 call 后固定 sleep request_interval_seconds。
    token_bucket = (
        rate_limiter_override
        if rate_limiter_override is not None
        else (
            TokenBucket(requests_per_minute)
            if requests_per_minute and requests_per_minute > 0
            else None
        )
    )
    # 用令牌桶时关掉 post-call 固定 sleep(避免双重限速把速率压到 RPM 以下)。
    post_sleep = 0.0 if token_bucket is not None else request_interval_seconds

    def rate_gate() -> None:
        """发请求前的限速闸门：启用令牌桶时阻塞取令牌，否则空操作(由 post_sleep 限速)。"""
        if token_bucket is not None:
            token_bucket.acquire()

    # 收集本次需要处理的 query（任一模式尚未成功完成）。
    accepted_queries: list[dict[str, Any]] = []
    for query_row in read_jsonl(queries_path):
        # 只处理通过筛选的查询(accepted)；默认 True 是为兼容没有该字段的老数据。
        if not query_row.get("accepted", True):
            continue
        # primary-only 砍量：只保留 fact_id 在白名单内的 query（None=不过滤）。
        if allowed_fact_ids is not None and str(query_row.get("fact_id")) not in allowed_fact_ids:
            continue
        if str(query_row.get("audit_id")) not in benchmark:
            raise RuntimeError(
                f"Accepted query references an audit_id outside the benchmark: "
                f"{query_row.get('query_id')}"
            )
        accepted_queries.append(query_row)
    full_accepted_query_count = len(accepted_queries)
    if schedule_path is not None:
        if not schedule_cell:
            raise ValueError("schedule_cell is required when schedule_path is set")
        ordinals: dict[str, int] = dict(schedule_ordinals_override or {})
        selected_block_query_ids: set[str] = set(
            schedule_block_query_ids_override or set()
        )
        if schedule_ordinals_override is None:
            for schedule_row in read_jsonl(schedule_path):
                if (
                    str(schedule_row.get("dataset")) == dataset
                    and str(schedule_row.get("cell")) == str(schedule_cell)
                ):
                    query_id = str(schedule_row.get("query_id") or "")
                    if query_id in ordinals:
                        raise RuntimeError(
                            f"Duplicate schedule identity for "
                            f"{dataset}/{schedule_cell}/{query_id}"
                        )
                    ordinals[query_id] = int(schedule_row["ordinal"])
                    if (
                        schedule_block_id is not None
                        and str(schedule_row.get("block_id")) == schedule_block_id
                    ):
                        selected_block_query_ids.add(query_id)
        accepted_ids = {str(row["query_id"]) for row in accepted_queries}
        if set(ordinals) != accepted_ids:
            raise RuntimeError(
                f"Schedule/query identity mismatch for {dataset}/{schedule_cell}"
            )
        accepted_queries = [
            {**row, "schedule_ordinal": ordinals[str(row["query_id"])]}
            for row in accepted_queries
            if schedule_block_id is None
            or str(row["query_id"]) in selected_block_query_ids
        ]
        if schedule_block_id is not None and len(accepted_queries) != 6:
            raise RuntimeError(
                f"Schedule block {schedule_block_id} must contain six queries "
                f"for {dataset}/{schedule_cell}"
            )
        accepted_queries.sort(key=lambda row: int(row["schedule_ordinal"]))
    fixed_budget = (
        validate_fixed_query_budget(
            accepted_queries,
            pairs_per_source,
            expected_source_keys=benchmark_source_keys,
            allow_shared_q_plus=allow_shared_q_plus,
        )
        if pairs_per_source is not None and schedule_block_id is None
        else {"enabled": False}
    )
    fixed_budget["enabled"] = pairs_per_source is not None
    if allow_shared_q_plus:
        fixed_budget["allow_shared_q_plus"] = True
    if schedule_block_id is not None:
        fixed_budget["deferred_to_full_schedule_finalize"] = True
    pending: list[dict[str, Any]] = []
    for query_row in accepted_queries:
        qid = str(query_row["query_id"])
        # 只要 RAG 或(启用了 LLM-only 时)LLM-only 任一边还没成功，就需要处理这条查询。
        if (run_rag and qid not in done_rag) or (run_llm_only and qid not in done_llm):
            pending.append(query_row)

    def process(query_row: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, int]:
        """检索并生成单个 query 的 RAG / LLM-only 响应。

        只读共享数据（benchmark / retriever / client）并返回新对象，无共享可变状态，
        因此可以安全地并发执行。所有写入与计数都留给主线程的消费循环。

        参数:
            query_row: 一条查询记录。
        返回:
            (rag_row, llm_row, fails)：两种模式各自的结果行(已完成的那边为 None)，
            以及本条查询里失败的请求次数。
        """
        query_id = str(query_row["query_id"])
        query = str(query_row["query"])
        attack_query = build_pcv_attack_request(query)
        # 按 audit_id 找到这条查询对应的样本，进而拿到"目标文档 id"。
        sample = benchmark.get(str(query_row["audit_id"]), {})
        target_doc_id = str(sample.get("doc_id", ""))
        target_source_key = str(
            sample.get("source_key")
            or query_row.get("source_key")
            or sample.get("source_id")
            or query_row.get("source_id")
            or target_doc_id
        )
        rag_row: dict[str, Any] | None = None
        llm_row: dict[str, Any] | None = None
        fails = 0

        # —— RAG 模式：只有这条查询的 RAG 还没成功时才跑 ——
        if run_rag and query_id not in done_rag:
            assert retriever is not None
            if normalized_context_control == "retrieved":
                retrieved = retriever.retrieve(attack_query, top_k=top_k)
            else:
                assert context_controller is not None
                oracle_chunks = context_controller.oracle(attack_query, target_source_key)
                if normalized_context_control == "oracle":
                    retrieved = oracle_chunks
                else:
                    retrieved = context_controller.random_matched(
                        query_id=query_id,
                        target_source_key=target_source_key,
                        oracle_chunks=oracle_chunks,
                    )
            retrieved_doc_ids = [item.doc_id for item in retrieved]
            retrieved_chunk_ids = [item.chunk_id for item in retrieved]
            retrieved_source_keys = [
                item.metadata.get("source_key") for item in retrieved
            ]
            retrieval_scores = [item.score for item in retrieved]
            retrieval_stage_scores = [
                item.metadata.get("retrieval_stage_scores") for item in retrieved
            ]
            contexts = [item.text for item in retrieved]
            response, error, response_metadata = _call_generator(
                client,
                build_rag_prompt(attack_query, contexts),
                temperature=temperature,
                timeout=timeout,
                max_tokens=max_tokens,
                retries=retries,
                retry_backoff_base=retry_backoff_base,
                retry_backoff_max=retry_backoff_max,
                retry_until_success=retry_until_success,
                retry_cooldown_seconds=retry_cooldown_seconds,
                before_attempt=rate_gate,
                return_metadata=True,
                expected_model_id=generator_id,
                require_provider_model_id=bool(generator_id),
            )
            if error is None:
                validate_fingerprint(response_metadata)
            # 每次请求后按配置歇一会儿(限速)；用令牌桶时 post_sleep=0(桶已限速)。
            _sleep_between_requests(post_sleep)
            if error:
                fails += 1
            rag_row = {
                "request_id": f"rag_req_{query_id}",
                "mode": "rag",
                "variant_id": variant,
                "query_id": query_id,
                "pair_id": query_row.get("pair_id"),
                "fact_id": query_row.get("fact_id"),
                "audit_id": query_row["audit_id"],
                "doc_id": query_row.get("doc_id"),
                "source_id": query_row.get("source_id") or query_row.get("doc_id"),
                "source_key": query_row.get("source_key") or query_row.get("source_id") or query_row.get("doc_id"),
                "claim_type": query_row.get("claim_type"),
                "dataset": dataset,
                "group": query_row["group"],
                "query": query,
                "attack_query": attack_query,
                "expected_entity": query_row.get("expected_entity") or query_row.get("original_entity"),
                "counterfactual_entity": query_row.get("counterfactual_entity") or query_row.get("conflict_entity"),
                "entity_type": query_row.get("entity_type"),
                "response": response,
                "retrieved_doc_ids": retrieved_doc_ids,
                "retrieved_chunk_ids": retrieved_chunk_ids,
                "retrieved_source_keys": retrieved_source_keys,
                "retrieval_scores": retrieval_scores,
                "retrieval_stage_scores": retrieval_stage_scores,
                # 记录"目标文档是否被检索到"，是分析检索是否命中的重要指标。
                "target_doc_retrieved": bool(target_doc_id and target_doc_id in retrieved_doc_ids),
                "target_source_retrieved": bool(
                    target_source_key
                    and target_source_key in set(retrieved_source_keys)
                ),
                "schedule_ordinal": query_row.get("schedule_ordinal"),
                "schedule_hash": schedule_hash,
                "generation_config": {"top_k": top_k, "temperature": temperature, "max_tokens": max_tokens},
                "error": error,
                "created_at": created_at,
                **response_metadata,
                "generator_family": generator_family,
                "concrete_model": effective_model,
                "generator_id": generator_id,
                "generator_version": generator_version,
                "retriever_backend": getattr(retriever, "retriever_backend", None),
                "retriever_id": (
                    retriever_identity_override
                    or getattr(retriever, "manifest", {}).get("retriever_id")
                ),
                "context_control": normalized_context_control,
            }

        # —— LLM-only 模式：该查询 LLM-only 还没成功、且未关闭该路时才跑 ——
        if run_llm_only and query_id not in done_llm:
            response, error, response_metadata = _call_generator(
                client,
                build_llm_only_prompt(attack_query),
                temperature=temperature,
                timeout=timeout,
                max_tokens=max_tokens,
                retries=retries,
                retry_backoff_base=retry_backoff_base,
                retry_backoff_max=retry_backoff_max,
                retry_until_success=retry_until_success,
                retry_cooldown_seconds=retry_cooldown_seconds,
                before_attempt=rate_gate,
                return_metadata=True,
                expected_model_id=generator_id,
                require_provider_model_id=bool(generator_id),
            )
            if error is None:
                validate_fingerprint(response_metadata)
            _sleep_between_requests(post_sleep)
            if error:
                fails += 1
            llm_row = _make_llm_row(
                query_row, response, error,
                dataset=dataset, temperature=temperature, max_tokens=max_tokens, created_at=created_at,
                variant_id=variant,
            )
            llm_row["attack_query"] = attack_query
            llm_row["generator_id"] = generator_id
            llm_row["generator_version"] = generator_version
            llm_row["generator_family"] = generator_family
            llm_row["concrete_model"] = effective_model
            llm_row.update(response_metadata)
        return rag_row, llm_row, fails

    rag_rows: list[dict[str, Any]] = []
    llm_rows: list[dict[str, Any]] = []
    completed = 0
    failures = 0

    # 并发线程数至少为 1；只有 >1 时才真正创建线程池。
    workers = max(1, int(max_workers))
    executor = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
    # executor.map 保持输入顺序，因此并发下写出的行序仍然确定、可复现。
    result_iter = executor.map(process, pending) if executor is not None else map(process, pending)
    try:
        # 逐条消费处理结果(单线程或多线程都走这同一个循环)。
        for rag_row, llm_row, fails in tqdm(result_iter, total=len(pending), desc=f"run rag/llm {dataset}", unit="query"):
            failures += fails
            if rag_row is not None:
                rag_rows.append(rag_row)
            if llm_row is not None:
                llm_rows.append(llm_row)
            completed += 1
            # 按配置的 checkpoint 间隔分批写盘，降低中断后的重复请求量。
            if len(rag_rows) >= checkpoint_every:
                write_jsonl(rag_rows, rag_output, append=append_rag)
                append_rag = True
                rag_rows.clear()
            if len(llm_rows) >= checkpoint_every:
                write_jsonl(llm_rows, llm_output, append=append_llm)
                append_llm = True
                llm_rows.clear()
    finally:
        # 无论正常结束还是出错，都要关闭线程池、等所有线程收尾。
        if executor is not None:
            executor.shutdown(wait=True)

    # 把最后不足 checkpoint 间隔的剩余结果也写出去。
    if rag_rows:
        write_jsonl(rag_rows, rag_output, append=append_rag)
    if llm_rows:
        write_jsonl(llm_rows, llm_output, append=append_llm)

    rag_stats = compact_response_file(rag_output) if run_rag else {
        "input_rows": 0, "unique_queries": 0, "duplicates_removed": 0, "succeeded": 0, "failed": 0,
    }
    llm_stats = compact_response_file(llm_output) if run_llm_only else {
        "input_rows": 0, "unique_queries": 0, "duplicates_removed": 0, "succeeded": 0, "failed": 0,
    }
    planned = full_accepted_query_count
    metadata_rows: list[dict[str, Any]] = []
    for response_path, enabled in (
        (rag_output, run_rag),
        (llm_output, run_llm_only),
    ):
        if enabled and response_path.is_file():
            metadata_rows.extend(read_jsonl(response_path))
    successful_metadata_rows = [
        row
        for row in metadata_rows
        if response_is_success(row)
    ]
    call_times = sorted(
        str(row["called_at"])
        for row in successful_metadata_rows
        if row.get("called_at")
    )
    provider_model_ids = sorted({
        str(row["provider_model_id"])
        for row in successful_metadata_rows
        if row.get("provider_model_id")
    })

    manifest = {
        "dataset": dataset,
        "variant_id": variant,
        "query_budget": planned,
        "query_budget_per_source": fixed_budget.get("queries_per_source"),
        "fixed_budget": fixed_budget,
        "generator_family": generator_family,
        "concrete_model": effective_model,
        "generator_id": generator_id,
        "generator_version": generator_version,
        "retriever_backend": (
            getattr(retriever, "retriever_backend", None) if retriever is not None else None
        ),
        "retriever_id": (
            (
                retriever_identity_override
                or getattr(retriever, "manifest", {}).get("retriever_id")
            )
            if retriever is not None
            else None
        ),
        "context_control": normalized_context_control,
        "ground_truth_source_store_hash": resume_identity[
            "ground_truth_source_store_hash"
        ],
        "schedule_hash": resume_identity["schedule_hash"],
        "schedule_cell": resume_identity["schedule_cell"],
        "index_manifest_hash": index_manifest_hash,
        "queries_path": str(queries_path),
        "queries_hash": sha256_file(queries_path),
        "query_hash": resume_identity["query_hash"],
        "benchmark_hash": resume_identity["benchmark_hash"],
        "code_commit": resume_identity["code_commit"],
        "experiment_identity": resume_identity,
        "provider_response_metadata": {
            "actual_model_ids": provider_model_ids,
            "request_ids_present": sum(
                bool(row.get("provider_request_id"))
                for row in successful_metadata_rows
            ),
            "system_fingerprints": sorted({
                str(row["system_fingerprint"])
                for row in successful_metadata_rows
                if row.get("system_fingerprint")
            }),
            "first_call_at": call_times[0] if call_times else None,
            "last_call_at": call_times[-1] if call_times else None,
            "input_tokens_total": sum(
                int(row.get("input_tokens") or 0)
                for row in successful_metadata_rows
            ),
            "output_tokens_total": sum(
                int(row.get("output_tokens") or 0)
                for row in successful_metadata_rows
            ),
            "finish_reasons": sorted({
                str(row["finish_reason"])
                for row in successful_metadata_rows
                if row.get("finish_reason") is not None
            }),
            "latency_ms_total": sum(
                float(row.get("latency_ms") or 0.0)
                for row in successful_metadata_rows
            ),
            "retry_count_total": sum(
                int(row.get("retry_count") or 0)
                for row in successful_metadata_rows
            ),
        },
        "source_whitelist_hash": sha256_obj(sorted({
            str(row.get("source_key") or row.get("source_id") or row.get("doc_id"))
            for row in accepted_queries
            if str(row.get("group")) in {"KB_Member", "True_Non_Member"}
        })),
        "benchmark_path": str(benchmark_path),
        "index_dir": str(index_dir),
        "rag_output_path": str(rag_output),
        "llm_output_path": str(llm_output),
        "planned_queries": planned,
        "attempted_queries": completed,
        "completed_queries": completed,
        "failures": failures,
        "rag_integrity": {
            **rag_stats,
            "missing": max(0, planned - rag_stats["succeeded"]) if run_rag else 0,
        },
        "llm_only_integrity": {
            **llm_stats,
            "missing": max(0, planned - llm_stats["succeeded"]) if run_llm_only else 0,
        },
        "max_workers": workers,
        "run_rag": run_rag,
        "run_llm_only": run_llm_only,
        "allowed_fact_ids_count": (len(allowed_fact_ids) if allowed_fact_ids is not None else None),
        "requests_per_minute": requests_per_minute,
        "checkpoint_every": checkpoint_every,
        "retry_until_success": retry_until_success,
        "retry_cooldown_seconds": retry_cooldown_seconds,
        "rate_limit_mode": "token_bucket" if token_bucket is not None else "fixed_interval",
        "created_at": created_at,
        "config_snapshot": config_snapshot or {},
    }
    # 两个输出各自配一份同样的 manifest，方便单独追溯。
    if run_rag:
        write_json(manifest, rag_output.with_suffix(".manifest.json"))
    if run_llm_only:
        write_json(manifest, llm_output.with_suffix(".manifest.json"))
    LOGGER.info(
        "Finished response run for %s: rag=%s llm_only=%s queries=%s failures=%s",
        dataset,
        run_rag,
        run_llm_only,
        completed,
        failures,
    )
    return manifest


def _call_generator(
    client: VictimClient,
    prompt: str,
    *,
    temperature: float,
    timeout: float,
    max_tokens: int,
    retries: int,
    retry_backoff_base: float,
    retry_backoff_max: float,
    retry_until_success: bool = False,
    retry_cooldown_seconds: float = 300.0,
    before_attempt: Callable[[], None] | None = None,
    return_metadata: bool = False,
    expected_model_id: str | None = None,
    require_provider_model_id: bool = False,
) -> Any:
    """带重试调用 generator。

    中文说明：封装"调用一次大模型生成回答"的逻辑，并在失败时按指数退避自动重试。

    参数:
        client:            大模型客户端。
        prompt:            提示词。
        temperature/timeout/max_tokens: 生成参数(见上面主函数说明)。
        retries:           最多额外重试次数。
        retry_backoff_base/retry_backoff_max: 控制短重试等待时间。
        retry_until_success: API/网络错误是否在短重试耗尽后继续长冷却重试。
        retry_cooldown_seconds: 长冷却时间。
        expected_model_id: 冻结的具体模型 ID；提供后必须与 provider 实际返回值一致。
        require_provider_model_id: 是否拒绝缺失 provider 实际模型 ID 的响应。
    返回:
        (response, error, metadata)：成功时 error 为 None。
    """
    retry_cycle = 0
    while True:
        last_exception: Exception | None = None
        last_response = ""
        last_metadata = {
            "provider_model_id": None,
            "provider_request_id": None,
            "system_fingerprint": None,
            "called_at": None,
            "input_tokens": None,
            "output_tokens": None,
            "finish_reason": None,
            "latency_ms": None,
            "retry_count": 0,
        }
        # 总共尝试 retries+1 次(第 1 次 + retries 次短重试)。
        for attempt in range(retries + 1):
            last_response = ""
            last_metadata = {
                "provider_model_id": None,
                "provider_request_id": None,
                "system_fingerprint": None,
                "called_at": None,
                "input_tokens": None,
                "output_tokens": None,
                "finish_reason": None,
                "latency_ms": None,
                "retry_count": 0,
            }
            try:
                if before_attempt is not None:
                    before_attempt()
                generate_with_metadata = getattr(
                    client,
                    "generate_with_metadata",
                    None,
                )
                if callable(generate_with_metadata):
                    result = generate_with_metadata(
                        prompt,
                        temperature=temperature,
                        timeout=timeout,
                        max_tokens=max_tokens,
                    )
                    response = getattr(result, "content", None)
                    if response is None and isinstance(result, dict):
                        response = result.get("content")
                    metadata = {
                        "provider_model_id": (
                            result.get("provider_model_id")
                            if isinstance(result, dict)
                            else getattr(result, "provider_model_id", None)
                        ),
                        "provider_request_id": (
                            result.get("provider_request_id")
                            if isinstance(result, dict)
                            else getattr(result, "provider_request_id", None)
                        ),
                        "system_fingerprint": (
                            result.get("system_fingerprint")
                            if isinstance(result, dict)
                            else getattr(result, "system_fingerprint", None)
                        ),
                        "called_at": (
                            result.get("called_at")
                            if isinstance(result, dict)
                            else getattr(result, "called_at", None)
                        ),
                        "input_tokens": (
                            result.get("input_tokens")
                            if isinstance(result, dict)
                            else getattr(result, "input_tokens", None)
                        ),
                        "output_tokens": (
                            result.get("output_tokens")
                            if isinstance(result, dict)
                            else getattr(result, "output_tokens", None)
                        ),
                        "finish_reason": (
                            result.get("finish_reason")
                            if isinstance(result, dict)
                            else getattr(result, "finish_reason", None)
                        ),
                        "latency_ms": (
                            result.get("latency_ms")
                            if isinstance(result, dict)
                            else getattr(result, "latency_ms", None)
                        ),
                        "retry_count": int(
                            (
                                result.get("retry_count", 0)
                                if isinstance(result, dict)
                                else getattr(result, "retry_count", 0)
                            )
                            or 0
                        )
                        + attempt
                        + retry_cycle * (retries + 1),
                    }
                else:
                    response = client.generate(
                        prompt,
                        temperature=temperature,
                        timeout=timeout,
                        max_tokens=max_tokens,
                    )
                    metadata = {
                        "provider_model_id": None,
                        "provider_request_id": None,
                        "system_fingerprint": None,
                        "called_at": datetime.now(timezone.utc).isoformat(),
                        "input_tokens": None,
                        "output_tokens": None,
                        "finish_reason": None,
                        "latency_ms": None,
                        "retry_count": attempt
                        + retry_cycle * (retries + 1),
                    }
                last_response = str(response or "")
                last_metadata = metadata
                validation_error = generator_response_error(
                    last_response,
                    provider_model_id=metadata.get("provider_model_id"),
                    expected_model_id=expected_model_id,
                    require_provider_model_id=require_provider_model_id,
                )
                if validation_error:
                    raise RuntimeError(validation_error)
                if return_metadata:
                    return last_response, None, metadata
                return last_response, None
            except Exception as exc:  # noqa: BLE001
                last_exception = exc
                if attempt >= retries or not is_retryable_generator_error(exc):
                    break
                delay = _retry_delay(attempt, retry_backoff_base, retry_backoff_max)
                LOGGER.warning(
                    "Generator call failed attempt=%s retry_in=%.1fs error=%s",
                    attempt + 1, delay, str(exc),
                )
                if delay > 0:
                    time.sleep(delay)
        assert last_exception is not None
        if not retry_until_success or not is_retryable_generator_error(last_exception):
            LOGGER.warning("Generator call failed after short retries error=%s", str(last_exception))
            failure_metadata = {
                **last_metadata,
                "called_at": (
                    last_metadata.get("called_at")
                    or datetime.now(timezone.utc).isoformat()
                ),
            }
            if return_metadata:
                return last_response, str(last_exception), failure_metadata
            return last_response, str(last_exception)
        retry_cycle += 1
        delay = max(0.0, float(retry_cooldown_seconds))
        LOGGER.warning(
            "Generator short retries exhausted; cooldown_cycle=%s retry_in=%.1fs error=%s",
            retry_cycle, delay, str(last_exception),
        )
        if delay > 0:
            time.sleep(delay)


def _retry_delay(attempt: int, retry_backoff_base: float, retry_backoff_max: float) -> float:
    """Return capped exponential backoff delay after a failed request.

    中文说明：计算第 attempt 次重试前要等待的秒数，采用"指数退避并封顶"策略——
    每多失败一次，等待时间翻倍，但不超过上限。这样能缓解服务器压力又不会等太久。

    参数:
        attempt:            当前是第几次失败(从 0 开始)。
        retry_backoff_base: 退避基数。
        retry_backoff_max:  等待时间上限。
    返回:
        本次应等待的秒数；base 或 cap <= 0 时返回 0(即不等待)。
    """
    base = max(0.0, float(retry_backoff_base))
    cap = max(0.0, float(retry_backoff_max))
    # 任一参数非正，视为"不退避"，直接返回 0。
    if base <= 0 or cap <= 0:
        return 0.0
    # 指数增长 base * 2^attempt，并用 cap 封顶。
    return min(cap, base * (2**attempt))


def _sleep_between_requests(seconds: float) -> None:
    """在两次请求之间睡眠指定秒数(限速)；秒数<=0 则不睡。"""
    delay = max(0.0, float(seconds))
    if delay > 0:
        time.sleep(delay)


def _successful_query_ids(path: str | Path) -> set[Any]:
    """Only successful responses are eligible for resume skipping.

    中文说明：扫描一个输出文件，找出"确实成功完成"的查询 id 集合，供断点续跑时跳过。
    只有同时满足"有 query_id、没有 error、回答非空"的行才算成功——避免把上次失败的
    查询误判成已完成而漏跑。

    参数:
        path: 某个模式的输出 jsonl 路径。
    返回:
        成功完成的 query_id 集合；文件不存在时返回空集合。
    """
    p = Path(path)
    if not p.exists():
        return set()
    done: set[Any] = set()
    for row in read_jsonl(p):
        if response_is_success(row):
            done.add(row["query_id"])
    return done
