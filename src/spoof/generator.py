"""Spoofed_Non_Member 生成模块。

Spoofed_Non_Member 是风格/实体密度实验对照组，来自 Spoof_Seed，
并且绝对不能进入 RAG 知识库。

中文说明
========
本文件把 Spoof_Seed(待伪造的种子文档)交给「兄弟模型」SiblingClient,用多种改写策略
(formal_rewrite、syntax_restructure、compression...)重写出多个候选,再用 judge 给每个候选
在自然度/流畅度/语义保持/实体保持/风格匹配等维度打分,只保留过阈值且去重后的样本作为
最终的 Spoofed_Non_Member。输入是 Spoof_Seed 与 KB_Member 两个 jsonl,输出是选中样本的
jsonl、全部候选的评分 jsonl,以及一份记录分布统计/相似度/哈希溯源的 manifest。
这类样本风格上像成员、实际却未入库,用于度量攻击对它们的误报率,只是实验对照组,不属于核心攻击方法。
"""

from __future__ import annotations

# Spoofed_Non_Member is retained as an experimental control group for
# style/entity-density stress tests. It is not part of the PCV-MIA core method.

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from ..data.filter import entity_signal_counts, metadata_for_text
from ..llm.sibling_client import SiblingClient
from ..rag.embeddings import DEFAULT_EMBEDDING_MODEL, build_embedding_model
from ..utils.hash import sha256_file, sha256_obj, sha256_text
from ..utils.io import read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)

# 默认的改写策略列表:每个候选会按下标轮流取一种策略,以制造风格多样的伪造文本。
DEFAULT_STRATEGIES = ["formal_rewrite", "syntax_restructure", "compression", "domain_style", "neutral_paraphrase"]
# 各评分维度的默认通过阈值(满分 10),候选必须在每一维都达标才算 passed。
DEFAULT_THRESHOLDS = {
    "naturalness": 8,
    "fluency": 8,
    "semantic_preservation": 8,
    "entity_preservation": 8,
    "style_match": 8,
}


def _complete_scores(scores: dict[str, Any], source_text: str, spoof_text: str) -> dict[str, int]:
    """补齐 judge 没返回的评分维度。

    judge 可能只给出部分维度;本函数对缺失维度用经验规则兜底(如长度比、实体密度差),
    并把所有分数裁剪到 1~10 区间。

    参数:
        scores:      judge 返回的原始评分(可能不全)。
        source_text: 原始种子文本。
        spoof_text:  改写后的伪造文本。
    返回:
        补齐并裁剪到 [1, 10] 的完整评分字典。
    """
    source_meta = metadata_for_text(source_text)
    spoof_meta = metadata_for_text(spoof_text)
    # 长度匹配度:短文本长度 / 长文本长度,越接近 1 表示长度越相近。
    length_ratio = min(len(source_text), len(spoof_text)) / max(1, max(len(source_text), len(spoof_text)))
    # 实体密度差:两段文本实体密度的绝对差,越小表示实体密度越接近。
    density_gap = abs(float(source_meta["entity_density"]) - float(spoof_meta["entity_density"]))
    completed = {
        "naturalness": int(scores.get("naturalness", 8)),
        "fluency": int(scores.get("fluency", 8)),
        "semantic_preservation": int(scores.get("semantic_preservation", 8)),
        "entity_preservation": int(scores.get("entity_preservation", 8)),
        # 风格匹配缺省时,按长度比是否够高粗略给 8 或 6 分。
        "style_match": int(scores.get("style_match", 8 if length_ratio >= 0.75 else 6)),
        # 长度匹配缺省时,直接用长度比 × 10 折算。
        "length_match": int(scores.get("length_match", round(10 * length_ratio))),
        # 实体密度匹配缺省时,密度差很小给 9,否则给 7。
        "entity_density_match": int(scores.get("entity_density_match", 9 if density_gap <= 0.05 else 7)),
    }
    # 统一把每个分数夹到合法区间 [1, 10]。
    return {key: max(1, min(10, int(value))) for key, value in completed.items()}


def _passed(scores: dict[str, int], thresholds: dict[str, int]) -> bool:
    """判断候选是否在所有阈值维度上都达标。

    参数:
        scores:     补齐后的候选评分。
        thresholds: 各维度的通过阈值。
    返回:
        每个阈值维度都 >= 对应阈值时返回 True,否则 False。
    """
    return all(int(scores.get(key, 0)) >= int(value) for key, value in thresholds.items())


def _distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """统计一批样本的长度、实体数量与实体类型分布。

    用于在 manifest 里对比 KB_Member 与 Spoofed_Non_Member 的分布是否相近。

    参数:
        rows: 样本列表,每条至少含 "text" 字段。
    返回:
        含 count、length、entity_count、entity_types 的统计字典。
    """
    lengths = [len(row.get("text", "")) for row in rows]
    entity_counts = [int(metadata_for_text(row.get("text", ""))["entity_count"]) for row in rows]
    entity_type_counter: Counter[str] = Counter()
    for row in rows:
        # 逐条累加各类实体信号,汇总出整批样本的实体类型分布。
        counts = entity_signal_counts(row.get("text", ""))
        for key, value in counts.items():
            if value:
                entity_type_counter[key] += int(value)
    return {
        "count": len(rows),
        "length": {"avg": mean(lengths) if lengths else 0.0, "min": min(lengths) if lengths else 0, "max": max(lengths) if lengths else 0},
        "entity_count": {
            "avg": mean(entity_counts) if entity_counts else 0.0,
            "min": min(entity_counts) if entity_counts else 0,
            "max": max(entity_counts) if entity_counts else 0,
        },
        "entity_types": dict(entity_type_counter),
    }


def _similarity_stats(
    kb_rows: list[dict[str, Any]],
    spoof_rows: list[dict[str, Any]],
    model_name: str = DEFAULT_EMBEDDING_MODEL,
) -> dict[str, Any]:
    """估计 KB_Member 和 Spoofed_Non_Member 的 embedding 相似度分布。

    把伪造样本编码成向量,与知识库成员向量做内积,统计每条伪造样本对成员的最大相似度;
    用于检验伪造样本是否过于贴近真实成员(过近则不适合作干净的对照组)。

    参数:
        kb_rows:    KB_Member 样本(含 "text")。
        spoof_rows: Spoofed_Non_Member 样本(含 "text")。
        model_name: 用于编码的 embedding 模型名。
    返回:
        含 avg_max_similarity、max_similarity、num_pairs 的统计字典;任一为空则返回全 0。
    """
    if not kb_rows or not spoof_rows:
        return {"avg_max_similarity": 0.0, "max_similarity": 0.0, "num_pairs": 0}
    embedder = build_embedding_model(model_name, backend="auto")
    # 双侧各最多抽 500 条,控制相似度矩阵规模,避免大数据集下计算爆炸。
    kb_sample = kb_rows[: min(500, len(kb_rows))]
    spoof_sample = spoof_rows[: min(500, len(spoof_rows))]
    kb_vec = embedder.encode([row["text"] for row in kb_sample])
    spoof_vec = embedder.encode([row["text"] for row in spoof_sample])
    # 相似度矩阵:行=伪造样本,列=成员样本;取每行最大值即各伪造样本最贴近的成员相似度。
    sims = spoof_vec @ kb_vec.T
    max_sims = sims.max(axis=1).tolist()
    return {
        "avg_max_similarity": mean(max_sims) if max_sims else 0.0,
        "max_similarity": max(max_sims) if max_sims else 0.0,
        "num_pairs": len(max_sims),
    }


def generate_spoofed_nonmembers(
    dataset: str,
    spoof_seed_path: str | Path,
    kb_member_path: str | Path,
    output_path: str | Path,
    manifest_path: str | Path,
    client: SiblingClient | None = None,
    candidates_per_seed: int = 3,
    strategies: list[str] | None = None,
    thresholds: dict[str, int] | None = None,
    max_per_seed: int = 1,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    resume: bool = True,
    force: bool = False,
    config_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从 Spoof_Seed 生成最终 Spoofed_Non_Member JSONL。

    对每条种子轮流套用多种改写策略生成候选,用 judge 打分并补齐,过阈值且去重后选入最终样本;
    最后写出选中样本、全部候选评分,以及含分布统计与哈希溯源的 manifest。

    参数:
        dataset:             数据集名(写入产物并用于日志)。
        spoof_seed_path:     Spoof_Seed 种子 jsonl 路径(输入)。
        kb_member_path:      KB_Member 成员 jsonl 路径,仅用于分布/相似度对比。
        output_path:         选中 Spoofed_Non_Member 的输出 jsonl 路径。
        manifest_path:       manifest(统计与溯源)输出路径。
        client:              用于改写与评分的兄弟模型客户端,缺省则报错。
        candidates_per_seed: 每条种子尝试生成的候选数。
        strategies:          改写策略列表,缺省用 DEFAULT_STRATEGIES。
        thresholds:          各维度通过阈值,缺省用 DEFAULT_THRESHOLDS。
        max_per_seed:        每条种子最多选入的样本数(去重后)。
        embedding_model:     相似度统计使用的 embedding 模型名。
        resume:              产物已存在时是否跳过(配合 force)。
        force:               为 True 时强制重算,忽略已有产物。
        config_snapshot:     写入 manifest 的配置快照(用于复现)。
    返回:
        写入 manifest 的统计字典;若跳过已有产物,则返回带 skipped_existing 的简要字典。
    异常:
        ValueError: 未提供 client 时抛出。
    """
    output = Path(output_path)
    manifest = Path(manifest_path)
    # 断点续跑:开启 resume 且非 force 时,产物与 manifest 都已存在则直接跳过。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest.exists():
        LOGGER.info("Skipping existing spoofed non-members for %s: %s", dataset, output)
        return {"dataset": dataset, "output_path": str(output), "skipped_existing": True}

    if client is None:
        raise ValueError("generate_spoofed_nonmembers requires a configured SiblingClient.")
    strategies = strategies or DEFAULT_STRATEGIES
    thresholds = thresholds or DEFAULT_THRESHOLDS
    selected: list[dict[str, Any]] = []
    scored_candidates: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    created_at = datetime.now(timezone.utc).isoformat()

    for seed in tqdm(read_jsonl(spoof_seed_path), desc=f"spoofed {dataset}", unit="seed"):
        source_seed_id = str(seed.get("sample_id") or seed.get("doc_id"))
        per_seed_selected = 0
        for cand_idx in range(int(candidates_per_seed)):
            # 按候选序号轮流取策略,使同一种子的多个候选覆盖不同改写风格。
            strategy = strategies[cand_idx % len(strategies)]
            for rewrite in client.rewrite(seed["text"], strategy=strategy, n=1):
                digest = sha256_text(rewrite)
                # 用 judge 对改写结果逐维打分,再补齐缺失维度。
                judgement = client.judge_spoof(seed["text"], rewrite)
                scores = _complete_scores(judgement.get("scores", {}), seed["text"], rewrite)
                candidate = {
                    "dataset": dataset,
                    "source_seed_id": source_seed_id,
                    "rewrite_strategy": strategy,
                    "text": rewrite,
                    "text_hash": digest,
                    "spoof_scores": scores,
                    "judge_reason": judgement.get("judge_reason"),
                    "passed": _passed(scores, thresholds),
                }
                scored_candidates.append(candidate)
                # 选入条件:达标 + 文本未重复(按哈希去重)+ 该种子尚未选满。
                if candidate["passed"] and digest not in seen_hashes and per_seed_selected < int(max_per_seed):
                    seen_hashes.add(digest)
                    selected.append(
                        {
                            "doc_id": f"{dataset}_spoof_{len(selected):06d}",
                            "dataset": dataset,
                            "group": "Spoofed_Non_Member",
                            # 明确标注为实验对照组,且绝不入库(in_knowledge_base=False)。
                            "experimental_role": "experimental_control_group",
                            "source_seed_id": source_seed_id,
                            "text": rewrite,
                            "text_hash": digest,
                            "in_knowledge_base": False,
                            "spoof_scores": scores,
                            "metadata": {
                                "rewrite_strategy": strategy,
                                "created_at": created_at,
                                "source_text_hash": seed.get("text_hash"),
                            },
                        }
                    )
                    per_seed_selected += 1

    write_jsonl(selected, output)
    # 同时落盘全部候选(含未选中的)的评分,便于后续分析筛选过程。
    scored_path = output.with_name("spoofed_non_member_scored_candidates.jsonl")
    write_jsonl(scored_candidates, scored_path)
    kb_rows = list(read_jsonl(kb_member_path))
    style_scores = [int(row["spoof_scores"].get("style_match", 0)) for row in selected]
    manifest_obj = {
        "dataset": dataset,
        "output_path": str(output),
        "scored_candidates_path": str(scored_path),
        "created_at": created_at,
        "candidates": len(scored_candidates),
        "selected": len(selected),
        "experimental_role": "experimental_control_group",
        "method_role": "control_only_not_core_method",
        "thresholds": thresholds,
        "kb_member_hash": sha256_file(kb_member_path),
        "spoof_seed_hash": sha256_file(spoof_seed_path),
        "output_hash": sha256_file(output),
        "config_hash": sha256_obj(config_snapshot or {}),
        "config_snapshot": config_snapshot or {},
        "distribution_stats": {
            "kb_member": _distribution(kb_rows),
            "spoofed_non_member": _distribution(selected),
            "embedding_similarity": _similarity_stats(kb_rows, selected, model_name=embedding_model),
            "style_match": {
                "avg": mean(style_scores) if style_scores else 0.0,
                "min": min(style_scores) if style_scores else 0,
                "max": max(style_scores) if style_scores else 0,
            },
        },
    }
    write_json(manifest_obj, manifest)
    LOGGER.info("Generated Spoofed_Non_Member for %s: selected=%s candidates=%s", dataset, len(selected), len(scored_candidates))
    return manifest_obj
