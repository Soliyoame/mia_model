"""PCV-MIA L2 shadow 编排：建 K 个 Reserve-shadow 索引并估计 per-example 非成员零分布。

中文说明
========
L2(per-example offline LiRA)的"造世界"环节。L1 用 Reserve 群体的一个全局 (μ,σ) 做
单调变换，扣不掉 per-example 先验泄漏(诊断 enron formal: cvg_llm AUC=0.606)。L2 改为
**对每个评估目标 x 估计它自己的非成员零分布**：

  1. 从 Reserve(同分布、非成员、与评估组 source 互斥)采 K 个子集，各建一个 shadow 索引。
     因 Reserve 与所有评估目标(KB_Member / True_Non_Member)互斥，K 个 shadow 对全体目标
     天然都是 OUT 世界 —— 无需"每个 x 单独建不含 x 的库"，K 个 shadow 全体共享。
  2. 对评估 query 在每个 shadow 上跑 RAG(只跑 RAG 路：LLM-only 与索引无关、跨 shadow 不变，
     复用主 run 的，省 K 倍 LLM-only 调用)。
  3. 解析 stance、算 cvg_rag。同一目标 x 在 K 个 shadow 上的 cvg_rag 即为它的 OUT 分布。

下游 src/scoring/calibration.py 的 calibrate_l2_shadow 用这 K 份分数估 μ_out(x)/σ_out(x)，
对 victim 观测做 per-example z-score / offline LiRA 单边 p 值。

shadow 索引绝不参与"判定某文档是否成员"的 victim 检索，只服务于先验校准。
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from .index_builder import build_rag_index
from .runner import run_rag_and_llm_only
from ..parsing.stance_parser import parse_stance_files
from ..scoring.pcv_scorer import compute_pcv_scores
from ..llm.victim_client import VictimClient
from ..utils.io import ensure_dir, read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)

CALIBRATION_GROUP = "Reserve"
# shadow 上只需跑"评估目标"(成员候选)的 query；Reserve 自己的 query 不必跑，省成本。
EVAL_GROUPS = ("KB_Member", "True_Non_Member")


def _filter_eval_queries(queries_path: str | Path, out_path: Path, whitelist: set[str] | None = None) -> int:
    """过滤出评估目标(KB_Member / True_Non_Member)的 accepted query，写到 out_path。

    Reserve 是校准源不是评估目标，其 query 不必在 shadow 上跑，过滤掉可省约 1/3 调用。
    whitelist 非空时，只保留这些 audit_id 的 query(用于小规模探路，大降 API 调用量)。
    """
    rows = [
        r for r in read_jsonl(queries_path)
        if r.get("accepted", True) and str(r.get("group")) in EVAL_GROUPS
        and (whitelist is None or str(r.get("audit_id")) in whitelist)
    ]
    write_jsonl(rows, out_path)
    return len(rows)


def _select_eval_audits(queries_path: str | Path, limit: int, seed: int) -> set[str]:
    """从评估目标里每组各随机采样部分 audit，返回白名单(用于小规模探路)。

    按 group 聚合 audit_id，每组采样约 limit/组数 个，保留这些 audit 的全部 Q+/Q- query
    (成对完整才能算 cvg)。固定 seed 保证可复现。
    """
    import random as _random
    by_group: dict[str, set[str]] = {}
    for r in read_jsonl(queries_path):
        if r.get("accepted", True) and str(r.get("group")) in EVAL_GROUPS:
            by_group.setdefault(str(r.get("group")), set()).add(str(r.get("audit_id")))
    rng = _random.Random(seed)
    per = max(1, limit // max(1, len(by_group)))
    whitelist: set[str] = set()
    for aids in by_group.values():
        ordered = sorted(aids)
        rng.shuffle(ordered)
        whitelist |= set(ordered[:per])
    return whitelist


def run_l2_shadows(
    dataset: str,
    reserve_path: str | Path,
    queries_path: str | Path,
    benchmark_path: str | Path,
    main_llm_responses_path: str | Path,
    shadow_index_root: str | Path,
    shadow_output_root: str | Path,
    client: VictimClient | None = None,
    *,
    num_shadows: int = 4,
    sample_ratio: float = 0.8,
    shadow_size: int | None = None,
    eval_audit_limit: int | None = None,
    seed: int = 42,
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    embedding_backend: str = "auto",
    embedding_dim: int = 384,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    top_k: int = 5,
    temperature: float = 0.0,
    max_tokens: int = 512,
    timeout: float = 60.0,
    retries: int = 2,
    retry_backoff_base: float = 2.0,
    retry_backoff_max: float = 60.0,
    request_interval_seconds: float = 0.0,
    max_workers: int = 1,
    unknown_lambda: float = 0.5,
    refusal_penalty: float = 0.5,
    false_acceptance_penalty_value: float = 1.0,
    thresholds: list[float] | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """建 K 个 Reserve-shadow 并产出每个 shadow 的 audit 级 cvg_rag 分数。

    参数:
        dataset:                 数据集名。
        reserve_path:            Reserve 组 jsonl(shadow 文档来源)。
        queries_path:            stealth 过滤后的配对 query(与主 run 同一批)。
        benchmark_path:          攻击基准(供 runner 查 target_doc_id)。
        main_llm_responses_path: 主 run 的 LLM-only 回答(shadow 复用，不重跑 LLM-only)。
        shadow_index_root:       shadow 索引根目录(每个 shadow 一个子目录)。
        shadow_output_root:      shadow 中间产物(rag/stance/scores)根目录。
        client:                  victim 客户端(shadow generator 必须与 victim 同款)。
        num_shadows:             shadow 数量 K(offline 版 4~16 通常够拟合)。
        sample_ratio:            每个 shadow 从 Reserve 无放回采样的比例(<1 才有多样性)。
        shadow_size:             每个 shadow 的文档数；给定则覆盖 sample_ratio。
        eval_audit_limit:        非空时只在随机采样的这么多个评估 audit 上跑 shadow(小规模探路，
                                 大降 API 调用量；统计较糙，仅验证 L2 机制方向)。
        seed:                    采样基种子(第 k 个 shadow 用 seed+k)。
        其余:                    embedding / 切块 / 生成 / 打分参数，与主流水线一致。
        resume/force:            透传给底层各步，支持断点续跑(shadow 昂贵，强烈建议 resume)。
    返回:
        manifest：含每个 shadow 的分数路径列表 shadow_score_paths 等。
    异常:
        ValueError: 未提供 client，或 Reserve 为空时抛出。
    """
    if client is None:
        raise ValueError("run_l2_shadows requires a configured VictimClient.")
    thresholds = thresholds or [0.3, 0.5, 0.7, 1.0]
    idx_root = ensure_dir(shadow_index_root)
    out_root = ensure_dir(shadow_output_root)

    reserve = list(read_jsonl(reserve_path))
    if not reserve:
        raise ValueError(f"Reserve split is empty: {reserve_path}")
    # 每个 shadow 的文档数：显式 shadow_size 优先，否则按比例；至少 1。
    size = int(shadow_size) if shadow_size else max(1, int(len(reserve) * float(sample_ratio)))
    size = min(size, len(reserve))
    if size >= len(reserve):
        LOGGER.warning(
            "shadow_size(%s) >= Reserve(%s)：各 shadow 将相同、零分布无多样性(σ_out≈0)，"
            "L2 会退化。请增大 Reserve 或调小 sample_ratio。", size, len(reserve),
        )

    # 只在评估目标(KB/True_Non)的 query 上跑 shadow，省成本。
    # eval_audit_limit 非空时进一步只跑随机采样的少量 audit(小规模探路)。
    whitelist = _select_eval_audits(queries_path, eval_audit_limit, seed) if eval_audit_limit else None
    eval_queries_path = out_root / f"{dataset}_eval_queries.jsonl"
    n_eval_q = _filter_eval_queries(queries_path, eval_queries_path, whitelist=whitelist)
    LOGGER.info(
        "L2 shadow: K=%s, shadow_size=%s/%s, eval_queries=%s%s",
        num_shadows, size, len(reserve), n_eval_q,
        (f" (探路采样 {len(whitelist)} 个 audit)" if whitelist else ""),
    )

    shadow_score_paths: list[str] = []
    for k in range(num_shadows):
        tag = f"shadow_{k:02d}"
        # 1) 无放回子采样 Reserve（第 k 个用 seed+k，可复现且各 shadow 不同）。
        rng = random.Random(seed + k)
        subset = rng.sample(reserve, size)
        docs_path = out_root / f"{dataset}_{tag}_docs.jsonl"
        write_jsonl(subset, docs_path)

        # 2) 建 shadow 索引（allowed_group="Reserve"）。
        index_dir = ensure_dir(idx_root / tag)
        build_rag_index(
            dataset=f"{dataset}_{tag}",
            kb_member_path=docs_path,
            output_dir=index_dir,
            embedding_model=embedding_model,
            embedding_backend=embedding_backend,
            embedding_dim=embedding_dim,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            resume=resume,
            force=force,
            allowed_group=CALIBRATION_GROUP,
        )

        # 3) 在 shadow 索引上只跑 RAG（run_llm_only=False）。
        rag_path = out_root / f"{dataset}_{tag}_rag.jsonl"
        llm_unused = out_root / f"{dataset}_{tag}_llm_unused.jsonl"
        run_rag_and_llm_only(
            dataset=f"{dataset}_{tag}",
            queries_path=eval_queries_path,
            benchmark_path=benchmark_path,
            index_dir=index_dir,
            rag_output_path=rag_path,
            llm_output_path=llm_unused,
            client=client,
            top_k=top_k,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            retries=retries,
            retry_backoff_base=retry_backoff_base,
            retry_backoff_max=retry_backoff_max,
            request_interval_seconds=request_interval_seconds,
            max_workers=max_workers,
            resume=resume,
            force=force,
            run_llm_only=False,
        )

        # 4) 解析 stance：shadow 的 RAG 回答 + 主 run 的 LLM-only 回答(复用)。
        stance_path = out_root / f"{dataset}_{tag}_stance.jsonl"
        parse_stance_files(
            dataset=f"{dataset}_{tag}",
            queries_path=eval_queries_path,
            rag_responses_path=rag_path,
            llm_responses_path=main_llm_responses_path,
            output_path=stance_path,
            resume=resume,
            force=force,
        )

        # 5) 打分：取每个 audit 的 cvg_rag(基于 shadow 检索)作为该 shadow 的 OUT 样本。
        scores_path = out_root / f"{dataset}_{tag}_scores.jsonl"
        compute_pcv_scores(
            dataset=f"{dataset}_{tag}",
            parsed_stance_path=stance_path,
            output_path=scores_path,
            unknown_lambda=unknown_lambda,
            refusal_penalty=refusal_penalty,
            false_acceptance_penalty_value=false_acceptance_penalty_value,
            thresholds=thresholds,
            resume=resume,
            force=force,
        )
        shadow_score_paths.append(str(scores_path))
        LOGGER.info("L2 shadow %s done -> %s", tag, scores_path)

    manifest = {
        "dataset": dataset,
        "num_shadows": num_shadows,
        "shadow_size": size,
        "reserve_total": len(reserve),
        "sample_ratio": sample_ratio,
        "seed": seed,
        "eval_queries": n_eval_q,
        "eval_audit_limit": eval_audit_limit,
        "eval_audit_whitelist": sorted(whitelist) if whitelist else None,
        "shadow_score_paths": shadow_score_paths,
        "shadow_index_root": str(idx_root),
        "shadow_output_root": str(out_root),
    }
    write_json(manifest, out_root / f"{dataset}_shadow_manifest.json")
    return manifest
