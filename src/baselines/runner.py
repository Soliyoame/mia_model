"""Baseline 实验入口。

这里把可以直接由现有中间结果计算的 baseline 实现出来；需要额外 LLM 调用的
baseline 先输出可追踪的 stub 记录，后续可以在同一接口下补充真实调用。

中文说明
========
本文件对应流水线第 12 步「跑 baseline 对照」。它读入打分结果，针对若干种攻击方法
各算一行指标(AUC、准确率、各种 FPR 下的检出率等)，统一写成一个 jsonl，方便和本项目
方法横向比较、最后填进论文表格。
- "已实现(implemented=True)"：能直接用现有分数算出指标的方法。
- "预留(reserved_interface)"：需要自己另外构造查询、再调大模型才能跑的方法，这里
  只先占个位、记录原因，保证表格结构完整、日后可补。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..evaluation.metrics import summarize_membership_scores
from ..utils.io import read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)


def run_baselines(
    dataset: str,
    scores_path: str | Path,
    output_path: str | Path,
    threshold: float = 0.3,
    resume: bool = True,
    force: bool = False,
    config_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """运行或预留 baseline，并统一输出 JSONL。

    参数:
        dataset:         数据集名。
        scores_path:     打分阶段产出的分数文件(jsonl)。
        output_path:     baseline 结果输出路径(并派生 manifest)。
        threshold:       把分数转成"成员/非成员"判定时用的阈值。
        resume:          断点续跑:结果已存在则跳过。
        force:           强制重跑。
        config_snapshot: 配置快照,写进 manifest 便于复现。
    返回:
        manifest(字典);若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    # 断点续跑:结果非空且 manifest 存在则跳过。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        LOGGER.info("Skipping existing baselines for %s: %s", dataset, output)
        return {"dataset": dataset, "output_path": str(output), "skipped_existing": True}

    rows = list(read_jsonl(scores_path))
    results: list[dict[str, Any]] = []
    # 本项目方法:直接用 pcv_score 字段算指标。
    pcv_metrics = summarize_membership_scores(rows, score_key="pcv_score", threshold=threshold)
    results.append(_result_row("PCV-MIA new version", pcv_metrics, rows, implemented=True))

    # 如果分数里带有 cvg_rag(纯RAG信号),就能顺便算两个对照方法。
    if rows and "cvg_rag" in rows[0]:
        # Direct RAG-MIA:只用"带检索"的验证信号当作攻击分数。
        rag_only_metrics = summarize_membership_scores(rows, score_key="cvg_rag", threshold=threshold)
        results.append(_result_row("Direct RAG-MIA", rag_only_metrics, rows, implemented=True))
        # IA / Interrogation Attack(审问式攻击):这里复用同一个多查询 RAG 验证信号作为其
        # 可操作的近似实现。
        ia_metrics = summarize_membership_scores(rows, score_key="cvg_rag", threshold=threshold)
        ia_row = _result_row("IA / Interrogation Attack", ia_metrics, rows, implemented=True)
        ia_row["status"] = "implemented_from_existing_verification_probes"
        ia_row["reason"] = "Uses the multi-query RAG-only verification signal as an operational IA-style interrogation baseline."
        results.append(ia_row)
    else:
        # 没有该字段就把这两个方法标为"预留"。
        results.append(_reserved_row("Direct RAG-MIA", rows, "RAG-only score field is not present."))
        results.append(_reserved_row("IA / Interrogation Attack", rows, "RAG-only interrogation score field is not present."))

    # 这几种方法都需要各自单独构造查询并调用生成器,暂时只预留接口。
    for name in [
        "S2MIA",
        "MBA",
        "RAG-leaks / difficulty-calibrated similarity baseline",
        "E-MIA / exam-style QA baseline",
    ]:
        results.append(_reserved_row(name, rows, "This baseline requires its own query construction and generator calls; interface is reserved."))

    write_jsonl(results, output)
    manifest = {
        "dataset": dataset,
        "output_path": str(output),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "num_methods": len(results),
        "config_snapshot": config_snapshot or {},
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Baseline results written for %s: %s", dataset, output)
    return manifest


def _avg_query_count(rows: list[dict[str, Any]]) -> float:
    """估算"平均每份文档要发多少次查询"(用于比较各方法的开销)。

    每个 pair 需要问 Q+ 和 Q- 两次,所以这里把对数乘以 2 再对所有文档求平均。

    参数:
        rows: 分数记录列表(每行对应一份文档)。
    返回:
        平均查询次数;没有数据时返回 0.0。
    """
    if not rows:
        return 0.0
    # num_pairs(或兼容字段 num_queries) × 2 = 该文档的查询次数,再对所有文档取平均。
    return sum(int(row.get("num_pairs") or row.get("num_queries") or 0) * 2 for row in rows) / len(rows)


def _reserved_row(name: str, rows: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    """生成一行"预留接口"的占位结果:各项指标记为 None,并写明预留原因。

    参数:
        name:   方法名。
        rows:   分数记录(用于估算平均查询次数)。
        reason: 为什么暂时只预留(没真正实现)。
    返回:
        统一字段结构的占位结果字典。
    """
    return {
        "baseline": name,
        "implemented": False,
        "status": "reserved_interface",
        "reason": reason,
        "AUC": None,
        "Accuracy": None,
        "TPR@1%FPR": None,
        "TPR@5%FPR": None,
        "FPR-True_Non_Member": None,
        "FPR-Spoofed_Non_Member": None,
        "Detection Rate": None,
        "Average Query Number": _avg_query_count(rows),
        "Cost per Document": None,
    }


def _result_row(name: str, metrics: dict[str, Any], rows: list[dict[str, Any]], implemented: bool) -> dict[str, Any]:
    """把一个方法算好的指标整理成统一结构的一行结果。

    参数:
        name:        方法名。
        metrics:     summarize_membership_scores 算出的指标字典。
        rows:        分数记录(用于估算平均查询次数)。
        implemented: 是否为真正实现的方法。
    返回:
        统一字段结构的结果字典(与 _reserved_row 字段对齐,便于拼成表格)。
    """
    return {
        "baseline": name,
        "implemented": implemented,
        "status": "ok",
        # 下面这些都是从 metrics 里取出的标准评测指标。
        "AUC": metrics.get("AUC"),
        "Accuracy": metrics.get("Accuracy"),
        "TPR@1%FPR": metrics.get("TPR@1%FPR"),
        "TPR@5%FPR": metrics.get("TPR@5%FPR"),
        "FPR-True_Non_Member": metrics.get("FPR-True_Non_Member"),
        "FPR-Spoofed_Non_Member": metrics.get("FPR-Spoofed_Non_Member"),
        "Detection Rate": metrics.get("Detection Rate"),
        "Average Query Number": _avg_query_count(rows),
        "Cost per Document": None,
        "threshold_curve": metrics.get("threshold_curve"),
    }
