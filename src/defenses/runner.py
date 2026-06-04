"""防御实验模块。

当前实现提供可运行的评估骨架和保守的离线模拟。真实论文实验应在 script 09 的
RAG generator 前接入这些 policy，然后重新跑 parse/score。

中文说明
========
本文件对应流水线第 14 步「跑防御」。它评估：如果在 RAG 系统里加入隐私保护策略，
本攻击还能不能成功。当前给出的是"骨架"——先算一遍没有防御时的攻击指标(基线)，
再列出几种防御策略的接口占位。真正要拿论文数据，需要把这些策略接到生成阶段、
让模型在"带防御"的条件下重新回答，然后重跑解析与打分。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..evaluation.metrics import summarize_membership_scores
from ..utils.io import read_jsonl, write_json
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)


def run_defense_experiments(
    dataset: str,
    scores_path: str | Path,
    output_path: str | Path,
    threshold: float = 0.3,
    resume: bool = True,
    force: bool = False,
    config_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """输出防御实验结果骨架。

    参数:
        dataset:         数据集名。
        scores_path:     打分阶段产出的分数文件。
        output_path:     防御实验报告输出路径(单个 JSON 文件)。
        threshold:       成员判定阈值。
        resume:          断点续跑:结果已存在则跳过。
        force:           强制重跑。
        config_snapshot: 配置快照。
    返回:
        report(字典):含"无防御时的攻击基线指标"和各防御策略的占位条目。
    """
    output = Path(output_path)
    # 断点续跑:结果文件非空则跳过。
    if resume and not force and output.exists() and output.stat().st_size > 0:
        LOGGER.info("Skipping existing defense results: %s", output)
        return {"dataset": dataset, "output_path": str(output), "skipped_existing": True}

    rows = list(read_jsonl(scores_path))
    # 自动挑选可用的成员分数字段:优先 pcv_score,其次 cg_cvg。
    score_key = next((key for key in ("pcv_score", "cg_cvg") if rows and key in rows[0]), None)
    if score_key is None:
        # 两个字段都没有:警告并退回用 pcv_score(此时指标会全为 0,提示数据有问题)。
        LOGGER.warning(
            "No known membership score field (pcv_score/cg_cvg) found in %s; "
            "defense baseline metrics will be all-zero.",
            scores_path,
        )
        score_key = "pcv_score"
    # 先算一遍"没有任何防御时"的攻击效果,作为对比基线。
    baseline = summarize_membership_scores(rows, score_key=score_key, threshold=threshold)
    policies = []
    # 逐个防御策略生成占位条目(名称 + 说明)。各项防御后指标暂为 None,待真实实验填。
    for name, description in [
        ("Conflict-aware Non-disclosure", "When query conflicts with retrieved context, disclose conflict but not exact value."),
        ("Entity Redaction", "Redact sensitive entities before generator sees retrieved context."),
        ("Query Similarity Filter", "Reject or degrade answers for queries too similar to KB documents."),
        ("Answer-without-Correction", "State inconsistency without outputting original_entity."),
    ]:
        policies.append(
            {
                "defense": name,
                "description": description,
                "implemented": False,
                "status": "reserved_policy_interface",
                # 下面这些是衡量防御好坏的指标:防御后攻击 AUC、泄露率、对正常问答的影响等。
                "attack_auc_after_defense": None,
                "tpr_at_1_fpr_after_defense": None,
                "conflict_acknowledgment_rate": None,
                "exact_entity_leakage_rate": None,
                "normal_rag_qa_accuracy_drop": None,
                "refusal_rate_increase": None,
                "privacy_utility_tradeoff": None,
            }
        )

    report = {
        "dataset": dataset,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline_attack_metrics": baseline,
        "defenses": policies,
        "note": "Defense policies are defined as interfaces. Re-run RAG generation with each policy enabled for final paper numbers.",
        "config_snapshot": config_snapshot or {},
    }
    write_json(report, output)
    LOGGER.info("Defense report written: %s", output)
    return report
